#include "SurvivalGameMode.h"

#include "ArenaProp.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyLight.h"
#include "LeaderBrainComponent.h"
#include "ResourceNode.h"
#include "Safehouse.h"
#include "SurvivalAssets.h"
#include "SurvivalGameState.h"
#include "SurvivalHUD.h"
#include "SurvivalPlayerController.h"
#include "SurvivalSpectatorPawn.h"
#include "SurvivorCharacter.h"
#include "ZombieCharacter.h"

namespace
{
	struct FSurvivorProfile
	{
		const TCHAR* Name;
		FLinearColor Color;
		float Bravery;
		float Cooperation;
		float Diligence;
		EResourceType Favourite;
	};

	// The first profile is the starting leader, the survivor the camera follows.
	const FSurvivorProfile Profiles[] = {
		{TEXT("Maya"), FLinearColor(0.1f, 0.35f, 0.8f), 0.75f, 0.85f, 0.7f, EResourceType::Wood},
		{TEXT("Jake"), FLinearColor(0.8f, 0.15f, 0.1f), 0.9f, 0.5f, 0.45f, EResourceType::Scrap},
		{TEXT("Priya"), FLinearColor(0.65f, 0.2f, 0.7f), 0.35f, 0.95f, 0.8f, EResourceType::Food},
		{TEXT("Tomas"), FLinearColor(0.85f, 0.6f, 0.1f), 0.55f, 0.6f, 0.9f, EResourceType::Wood},
		{TEXT("Lena"), FLinearColor(0.1f, 0.65f, 0.6f), 0.6f, 0.75f, 0.55f, EResourceType::Food},
		{TEXT("Ox"), FLinearColor(0.45f, 0.3f, 0.2f), 0.95f, 0.4f, 0.6f, EResourceType::Scrap},
		{TEXT("Sunny"), FLinearColor(0.95f, 0.85f, 0.3f), 0.3f, 0.7f, 0.75f, EResourceType::Food},
		{TEXT("Rook"), FLinearColor(0.3f, 0.3f, 0.35f), 0.7f, 0.3f, 0.5f, EResourceType::Scrap},
	};

	constexpr float Ground = 0.f;
}

ASurvivalGameMode::ASurvivalGameMode()
{
	PrimaryActorTick.bCanEverTick = true;

	GameStateClass = ASurvivalGameState::StaticClass();
	PlayerControllerClass = ASurvivalPlayerController::StaticClass();
	DefaultPawnClass = ASurvivalSpectatorPawn::StaticClass();
	HUDClass = ASurvivalHUD::StaticClass();
}

ASurvivalGameState* ASurvivalGameMode::GS() const
{
	return GetGameState<ASurvivalGameState>();
}

void ASurvivalGameMode::StartPlay()
{
	// Build the world before players spawn and BeginPlay runs.
	BuildLighting();
	BuildArena();
	SpawnSquad();

	GS()->OnNightfall.AddUObject(this, &ASurvivalGameMode::HandleNightfall);
	GS()->OnDawn.AddUObject(this, &ASurvivalGameMode::HandleDawn);
	GS()->AddLog(TEXT("Day 1. The squad has made camp. Gather supplies before dark."), FLinearColor(1.f, 0.9f, 0.5f));

	Super::StartPlay();

	if (ASurvivorCharacter* Leader = GS()->GetLeader())
	{
		Leader->LeaderBrain->RequestThink(TEXT("the squad just arrived at a new camp"));
	}
}

// --- World building ----------------------------------------------------------------------------

void ASurvivalGameMode::BuildLighting()
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	Sun = GetWorld()->SpawnActor<ADirectionalLight>(FVector(0, 0, 1000), FRotator(-45, 30, 0), Params);
	Sun->GetRootComponent()->SetMobility(EComponentMobility::Movable);
	if (UDirectionalLightComponent* SunLight = Cast<UDirectionalLightComponent>(Sun->GetLightComponent()))
	{
		SunLight->SetAtmosphereSunLight(true);
		SunLight->SetIntensity(8.f);
	}

	GetWorld()->SpawnActor<ASkyAtmosphere>(FVector::ZeroVector, FRotator::ZeroRotator, Params);

	Sky = GetWorld()->SpawnActor<ASkyLight>(FVector(0, 0, 500), FRotator::ZeroRotator, Params);
	Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
	Sky->GetLightComponent()->SetIntensity(1.f);

	Fog = GetWorld()->SpawnActor<AExponentialHeightFog>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	Fog->GetComponent()->SetMobility(EComponentMobility::Movable);
	Fog->GetComponent()->SetFogDensity(0.02f);

	UpdateSky();
	Sky->GetLightComponent()->RecaptureSky();
}

void ASurvivalGameMode::BuildArena()
{
	ASurvivalGameState* State = GS();
	const float Half = State->ArenaHalfSize;
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	// Ground: a slab whose top surface sits at Z = 0, plus a darker trampled patch under the camp.
	AArenaProp* Floor = GetWorld()->SpawnActor<AArenaProp>(FVector(0, 0, Ground - 50.f), FRotator::ZeroRotator, Params);
	Floor->Setup(SurvivalAssets::Cube(), FVector(Half * 2.4f / 100.f, Half * 2.4f / 100.f, 1.f), FLinearColor(0.12f, 0.16f, 0.07f), true);

	AArenaProp* CampGround = GetWorld()->SpawnActor<AArenaProp>(FVector(0, 0, Ground + 0.5f), FRotator::ZeroRotator, Params);
	CampGround->Setup(SurvivalAssets::Cylinder(), FVector(15.f, 15.f, 0.01f), FLinearColor(0.2f, 0.15f, 0.09f), false);

	State->Safehouse = GetWorld()->SpawnActor<ASafehouse>(FVector(0, 0, Ground), FRotator::ZeroRotator, Params);

	// Resource clusters in rings around the camp: food close-ish, wood mid, scrap far out (risk vs reward).
	struct FRing
	{
		EResourceType Type;
		int32 Count;
		float MinDist;
		float MaxDist;
		int32 Amount;
	};
	const FRing Rings[] = {
		{EResourceType::Food, 6, 1300.f, 2600.f, 6},
		{EResourceType::Wood, 7, 1600.f, 3200.f, 8},
		{EResourceType::Scrap, 5, 2600.f, 4000.f, 6},
	};
	for (const FRing& Ring : Rings)
	{
		for (int32 i = 0; i < Ring.Count; ++i)
		{
			FVector Point;
			int32 Tries = 0;
			do
			{
				const float Angle = FMath::FRandRange(0.f, 2.f * PI);
				const float Dist = FMath::FRandRange(Ring.MinDist, Ring.MaxDist);
				Point = FVector(FMath::Cos(Angle) * Dist, FMath::Sin(Angle) * Dist, Ground);
			}
			while (!IsClear(Point, 400.f) && ++Tries < 20);

			AResourceNode* Node = GetWorld()->SpawnActor<AResourceNode>(Point, FRotator(0, FMath::FRandRange(0.f, 360.f), 0), Params);
			Node->Setup(Ring.Type, Ring.Amount);
			State->Nodes.Add(Node);
		}
	}

	// Rocks and ruined walls the squad has to path around.
	for (int32 i = 0; i < 22; ++i)
	{
		FVector Point;
		int32 Tries = 0;
		do
		{
			Point = FVector(FMath::FRandRange(-Half, Half), FMath::FRandRange(-Half, Half), Ground);
		}
		while ((!IsClear(Point, 350.f) || Point.Size2D() < 1100.f) && ++Tries < 20);

		const bool bWall = FMath::RandBool();
		const FVector Scale = bWall ? FVector(FMath::FRandRange(3.f, 6.f), 0.5f, 2.f) : FVector(FMath::FRandRange(1.5f, 3.f));
		AArenaProp* Prop = GetWorld()->SpawnActor<AArenaProp>(Point + FVector(0, 0, 50.f * Scale.Z * (bWall ? 1.f : 0.6f)),
		                                                      FRotator(0, FMath::FRandRange(0.f, 360.f), 0), Params);
		Prop->Setup(bWall ? SurvivalAssets::Cube() : SurvivalAssets::Sphere(), Scale,
		            bWall ? FLinearColor(0.35f, 0.32f, 0.3f) : FLinearColor(0.25f, 0.25f, 0.24f), true);
		State->Obstacles.Add(Prop);
	}
}

bool ASurvivalGameMode::IsClear(const FVector& Point, float Radius) const
{
	const ASurvivalGameState* State = GS();
	if (State->Safehouse && State->Safehouse->IsInside(Point, Radius + 200.f))
	{
		return false;
	}
	for (const AResourceNode* Node : State->Nodes)
	{
		if (Node && FVector::Dist2D(Node->GetActorLocation(), Point) < Radius)
		{
			return false;
		}
	}
	for (const AArenaProp* Prop : State->Obstacles)
	{
		if (Prop && FVector::Dist2D(Prop->GetActorLocation(), Point) < Radius + Prop->GetAvoidanceRadius())
		{
			return false;
		}
	}
	return true;
}

void ASurvivalGameMode::SpawnSquad()
{
	ASurvivalGameState* State = GS();
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;

	const int32 Count = FMath::Clamp(SquadSize, 1, static_cast<int32>(UE_ARRAY_COUNT(Profiles)));
	for (int32 i = 0; i < Count; ++i)
	{
		const FSurvivorProfile& P = Profiles[i];
		const float Angle = 2.f * PI * i / Count;
		const FVector Spot(FMath::Cos(Angle) * 250.f, FMath::Sin(Angle) * 250.f, Ground + 100.f);

		ASurvivorCharacter* Survivor = GetWorld()->SpawnActor<ASurvivorCharacter>(Spot, FRotator(0, FMath::RadiansToDegrees(Angle), 0), Params);
		if (Survivor)
		{
			Survivor->InitSurvivor(P.Name, P.Color, P.Bravery, P.Cooperation, P.Diligence, P.Favourite, i == 0);
			State->Survivors.Add(Survivor);
		}
	}
}

// --- Zombies -----------------------------------------------------------------------------------

FVector ASurvivalGameMode::RandomEdgePoint() const
{
	const float Half = GS()->ArenaHalfSize;
	const float Along = FMath::FRandRange(-Half, Half);
	switch (FMath::RandRange(0, 3))
	{
	case 0: return FVector(Half, Along, Ground + 100.f);
	case 1: return FVector(-Half, Along, Ground + 100.f);
	case 2: return FVector(Along, Half, Ground + 100.f);
	default: return FVector(Along, -Half, Ground + 100.f);
	}
}

void ASurvivalGameMode::SpawnZombie(bool bNightWave)
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AdjustIfPossibleButAlwaysSpawn;

	AZombieCharacter* Zombie = GetWorld()->SpawnActor<AZombieCharacter>(RandomEdgePoint(), FRotator::ZeroRotator, Params);
	if (Zombie)
	{
		Zombie->InitZombie(GS()->Day, bNightWave);
		GS()->Zombies.Add(Zombie);
	}
}

void ASurvivalGameMode::HandleNightfall()
{
	// Waves grow every night.
	WaveRemaining = 3 + 3 * GS()->Day;
	WaveTimer = 0.f;

	if (ASurvivorCharacter* Leader = GS()->GetLeader())
	{
		Leader->LeaderBrain->RequestThink(TEXT("night has fallen and the horde is coming"));
	}
}

void ASurvivalGameMode::HandleDawn()
{
	WaveRemaining = 0;
	if (ASurvivorCharacter* Leader = GS()->GetLeader())
	{
		Leader->LeaderBrain->RequestThink(TEXT("the sun is rising, the squad survived the night"));
	}
}

// --- Per-frame ---------------------------------------------------------------------------------

void ASurvivalGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	ASurvivalGameState* State = GS();
	if (!State || State->bGameOver)
	{
		return;
	}

	// Night wave: zombies trickle in from the edges over the first part of the night.
	if (WaveRemaining > 0)
	{
		WaveTimer -= DeltaSeconds;
		if (WaveTimer <= 0.f)
		{
			WaveTimer = FMath::FRandRange(1.f, 3.f);
			--WaveRemaining;
			SpawnZombie(true);
		}
	}

	// A few wanderers by day keep gatherers on their toes.
	if (!State->IsNight())
	{
		WandererTimer -= DeltaSeconds;
		if (WandererTimer <= 0.f)
		{
			WandererTimer = FMath::FRandRange(14.f, 24.f);
			if (State->Zombies.Num() < 2 + State->Day)
			{
				SpawnZombie(false);
			}
		}
	}

	UpdateSky();

	// The sky light needs an occasional recapture to follow the changing sky.
	SkyRecaptureTimer -= DeltaSeconds;
	if (SkyRecaptureTimer <= 0.f)
	{
		SkyRecaptureTimer = 4.f;
		Sky->GetLightComponent()->RecaptureSky();
	}
}

void ASurvivalGameMode::UpdateSky()
{
	const ASurvivalGameState* State = GS();
	if (!State || !Sun)
	{
		return;
	}

	// Day spans [0, NightStart): the sun rises, arcs overhead and sets. Night: a dim, cold moon.
	const float F = State->DayFraction;
	ULightComponent* SunLight = Sun->GetLightComponent();
	if (!State->IsNight())
	{
		const float T = F / State->NightStart;
		const float Elevation = FMath::Sin(T * PI);
		Sun->SetActorRotation(FRotator(-(5.f + 70.f * Elevation), 30.f + 140.f * T, 0.f));
		SunLight->SetIntensity(1.5f + 8.f * Elevation);
		SunLight->SetLightColor(FMath::Lerp(FLinearColor(1.f, 0.55f, 0.3f), FLinearColor(1.f, 0.97f, 0.9f), Elevation));
		Sky->GetLightComponent()->SetIntensity(0.5f + 0.7f * Elevation);
		Fog->GetComponent()->SetFogDensity(0.02f);
	}
	else
	{
		const float T = (F - State->NightStart) / (1.f - State->NightStart);
		Sun->SetActorRotation(FRotator(-(25.f + 20.f * FMath::Sin(T * PI)), 200.f + 140.f * T, 0.f));
		SunLight->SetIntensity(0.4f);
		SunLight->SetLightColor(FLinearColor(0.45f, 0.55f, 1.f));
		Sky->GetLightComponent()->SetIntensity(0.12f);
		Fog->GetComponent()->SetFogDensity(0.06f);
	}
}
