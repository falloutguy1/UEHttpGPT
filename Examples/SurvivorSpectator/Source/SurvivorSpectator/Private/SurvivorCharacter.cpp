#include "SurvivorCharacter.h"

#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "LeaderBrainComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "SurvivalAssets.h"
#include "SurvivalGameState.h"
#include "SurvivorAIController.h"
#include "ZombieCharacter.h"

namespace
{
	const FVector BodyStanding(0, 0, -20);
	const FVector HeadStanding(0, 0, 68);

	FLinearColor ResourceColor(EResourceType Type)
	{
		switch (Type)
		{
		case EResourceType::Food: return FLinearColor(0.7f, 0.1f, 0.1f);
		case EResourceType::Wood: return FLinearColor(0.35f, 0.2f, 0.07f);
		case EResourceType::Scrap: return FLinearColor(0.5f, 0.55f, 0.6f);
		default: return FLinearColor::Black;
		}
	}

	const TCHAR* HelpLines[] = {
		TEXT("Help! They're on me!"),
		TEXT("I need backup over here!"),
		TEXT("Somebody get this thing off me!"),
		TEXT("Can't hold them alone!"),
	};

	const TCHAR* ThanksLines[] = {
		TEXT("Thanks... I owe you one."),
		TEXT("I thought I was done for."),
		TEXT("Back on my feet. Let's go."),
	};
}

ASurvivorCharacter::ASurvivorCharacter()
{
	PrimaryActorTick.bCanEverTick = true;

	AIControllerClass = ASurvivorAIController::StaticClass();
	AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;

	bUseControllerRotationYaw = false;
	GetCharacterMovement()->bOrientRotationToMovement = true;
	GetCharacterMovement()->RotationRate = FRotator(0, 540, 0);
	GetCharacterMovement()->MaxWalkSpeed = 380.f;

	Body = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(GetCapsuleComponent());
	Body->SetCollisionProfileName(TEXT("NoCollision"));
	Body->SetRelativeLocation(BodyStanding);
	Body->SetRelativeScale3D(FVector(0.6f, 0.6f, 1.3f));

	Head = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Head"));
	Head->SetupAttachment(GetCapsuleComponent());
	Head->SetCollisionProfileName(TEXT("NoCollision"));
	Head->SetRelativeLocation(HeadStanding);
	Head->SetRelativeScale3D(FVector(0.45f));

	Pack = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Pack"));
	Pack->SetupAttachment(GetCapsuleComponent());
	Pack->SetCollisionProfileName(TEXT("NoCollision"));
	Pack->SetRelativeLocation(FVector(-36, 0, 10));
	Pack->SetRelativeScale3D(FVector(0.25f, 0.45f, 0.5f));

	Weapon = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Weapon"));
	Weapon->SetupAttachment(GetCapsuleComponent());
	Weapon->SetCollisionProfileName(TEXT("NoCollision"));
	Weapon->SetRelativeLocation(FVector(10, 38, 0));
	Weapon->SetRelativeRotation(FRotator(-60, 0, 0));
	Weapon->SetRelativeScale3D(FVector(0.08f, 0.08f, 0.8f));

	LeaderBrain = CreateDefaultSubobject<ULeaderBrainComponent>(TEXT("LeaderBrain"));
}

void ASurvivorCharacter::InitSurvivor(const FString& InName, const FLinearColor& InColor, float InBravery, float InCooperation,
                                      float InDiligence, EResourceType InFavourite, bool bInLeader)
{
	SurvivorName = InName;
	Color = InColor;
	Bravery = InBravery;
	Cooperation = InCooperation;
	Diligence = InDiligence;
	Favourite = InFavourite;
	bIsLeader = bInLeader;
	RefreshLook();
}

void ASurvivorCharacter::BeginPlay()
{
	Super::BeginPlay();

	Body->SetStaticMesh(SurvivalAssets::Cylinder());
	Head->SetStaticMesh(SurvivalAssets::Sphere());
	Pack->SetStaticMesh(SurvivalAssets::Cube());
	Weapon->SetStaticMesh(SurvivalAssets::Cube());

	BodyMaterial = SurvivalAssets::Paint(Body, Color);
	SurvivalAssets::Paint(Head, FLinearColor(0.75f, 0.55f, 0.42f));
	PackMaterial = SurvivalAssets::Paint(Pack, FLinearColor::Black);
	SurvivalAssets::Paint(Weapon, FLinearColor(0.3f, 0.3f, 0.32f));
	RefreshLook();
}

void ASurvivorCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	SpeechTimer = FMath::Max(0.f, SpeechTimer - DeltaSeconds);
	if (SpeechTimer <= 0.f)
	{
		Speech.Reset();
	}
	HitFlash = FMath::Max(0.f, HitFlash - DeltaSeconds);
	AttackCooldown = FMath::Max(0.f, AttackCooldown - DeltaSeconds);

	// Ease the weapon back after a swing.
	Weapon->SetRelativeRotation(FMath::RInterpTo(Weapon->GetRelativeRotation(), FRotator(-60, 0, 0), DeltaSeconds, 8.f));

	if (bDead)
	{
		return;
	}

	if (bDowned)
	{
		BleedOut -= DeltaSeconds;
		if (BleedOut <= 0.f)
		{
			Die();
		}
		RefreshLook();
		return;
	}

	Fullness = FMath::Max(0.f, Fullness - 0.2f * DeltaSeconds);
	if (Fullness <= 0.f)
	{
		Health -= 1.f * DeltaSeconds;
		if (Health <= 0.f)
		{
			GoDown();
			return;
		}
	}
	else if (Fullness > 40.f && TimeSinceHurt() > 8.f)
	{
		Health = FMath::Min(MaxHealth, Health + 0.5f * DeltaSeconds);
	}

	const bool bCanSprint = bSprinting && Stamina > 5.f;
	Stamina = FMath::Clamp(Stamina + (bCanSprint ? -6.f : 2.f) * DeltaSeconds, 0.f, 100.f);
	GetCharacterMovement()->MaxWalkSpeed = bCanSprint ? 600.f : (Stamina < 15.f ? 300.f : 380.f);

	RefreshLook();
}

void ASurvivorCharacter::AddCarried(EResourceType Type)
{
	if (CarriedType != Type)
	{
		CarriedType = Type;
		CarriedAmount = 0;
	}
	CarriedAmount = FMath::Min(MaxCarry, CarriedAmount + 1);
}

void ASurvivorCharacter::ClearCarried()
{
	CarriedType = EResourceType::None;
	CarriedAmount = 0;
}

bool ASurvivorCharacter::TryAttack(AZombieCharacter* Target)
{
	if (!CanAct() || !Target || Target->IsDead() || AttackCooldown > 0.f)
	{
		return false;
	}

	const ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>();
	const int32 WeaponLevel = State ? State->WeaponLevel : 0;

	AttackCooldown = 0.9f - 0.2f * Diligence;
	Stamina = FMath::Max(0.f, Stamina - 3.f);
	Weapon->SetRelativeRotation(FRotator(-150, 0, 0));
	SetActorRotation(FRotator(0, (Target->GetActorLocation() - GetActorLocation()).Rotation().Yaw, 0));

	const float Damage = (14.f + 6.f * WeaponLevel) * (Stamina < 15.f ? 0.6f : 1.f);
	Target->ReceiveHit(Damage, this);
	return true;
}

void ASurvivorCharacter::ReceiveHit(float Damage, AActor* Attacker)
{
	if (!CanAct())
	{
		return;
	}

	Health -= Damage;
	HitFlash = 0.2f;
	LastHurtTime = GetWorld()->GetTimeSeconds();
	LastAttacker = Cast<AZombieCharacter>(Attacker);

	if (Health <= 0.f)
	{
		GoDown();
		return;
	}

	if (Health < 70.f && GetWorld()->GetTimeSeconds() - LastHelpCallTime > 12.f)
	{
		LastHelpCallTime = GetWorld()->GetTimeSeconds();
		Say(HelpLines[FMath::RandRange(0, UE_ARRAY_COUNT(HelpLines) - 1)]);
	}
}

void ASurvivorCharacter::GoDown()
{
	bDowned = true;
	Health = 0.f;
	BleedOut = 35.f;
	bSprinting = false;
	GetCharacterMovement()->StopMovementImmediately();
	ClaimedTarget = nullptr;

	// Lie on the ground.
	Body->SetRelativeLocationAndRotation(FVector(0, 0, -70), FRotator(90, 0, 0));
	Head->SetRelativeLocation(FVector(70, 0, -70));

	if (ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		State->AddLog(FString::Printf(TEXT("%s is down! %.0fs to save them."), *SurvivorName, BleedOut), FLinearColor(1.f, 0.35f, 0.25f));
		if (ASurvivorCharacter* Leader = State->GetLeader())
		{
			Leader->LeaderBrain->RequestThink(FString::Printf(TEXT("%s just went down and is bleeding out"), *SurvivorName));
		}
	}
	Say(TEXT("I'm down! Someone help me!"));
}

void ASurvivorCharacter::Revive(ASurvivorCharacter* Rescuer)
{
	if (!bDowned || bDead)
	{
		return;
	}

	bDowned = false;
	Health = 35.f;
	Body->SetRelativeLocationAndRotation(BodyStanding, FRotator::ZeroRotator);
	Head->SetRelativeLocation(HeadStanding);

	if (ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		State->AddLog(FString::Printf(TEXT("%s pulled %s back to their feet."), Rescuer ? *Rescuer->SurvivorName : TEXT("Someone"), *SurvivorName),
		              FLinearColor(0.4f, 1.f, 0.5f));
	}
	Say(ThanksLines[FMath::RandRange(0, UE_ARRAY_COUNT(ThanksLines) - 1)]);
}

void ASurvivorCharacter::Die()
{
	bDead = true;
	bDowned = false;
	Speech.Reset();
	GetCapsuleComponent()->SetCollisionResponseToChannel(ECC_Pawn, ECR_Ignore);
	Weapon->SetVisibility(false);
	Pack->SetVisibility(false);

	if (ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		State->AddLog(FString::Printf(TEXT("%s didn't make it."), *SurvivorName), FLinearColor(0.8f, 0.2f, 0.2f));
		State->EnsureLeader();
		if (ASurvivorCharacter* Leader = State->GetLeader())
		{
			Leader->LeaderBrain->RequestThink(FString::Printf(TEXT("%s has died"), *SurvivorName));
		}
	}
	RefreshLook();
}

void ASurvivorCharacter::Say(const FString& Line, float Duration)
{
	if (Line.IsEmpty() || bDead)
	{
		return;
	}
	Speech = Line;
	SpeechTimer = Duration;

	if (ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		State->AddLog(FString::Printf(TEXT("%s: \"%s\""), *SurvivorName, *Line), FMath::Lerp(Color, FLinearColor::White, 0.5f));
	}
}

void ASurvivorCharacter::SetSprinting(bool bSprint)
{
	bSprinting = bSprint;
}

float ASurvivorCharacter::TimeSinceHurt() const
{
	return GetWorld()->GetTimeSeconds() - LastHurtTime;
}

void ASurvivorCharacter::RefreshLook()
{
	if (BodyMaterial)
	{
		FLinearColor Tint = Color;
		if (bDead)
		{
			Tint = FLinearColor(0.08f, 0.08f, 0.08f);
		}
		else if (bDowned)
		{
			Tint = FMath::Lerp(Color, FLinearColor(0.5f, 0.f, 0.f), 0.5f + 0.3f * FMath::Sin(GetWorld()->GetTimeSeconds() * 6.f));
		}
		else if (HitFlash > 0.f)
		{
			Tint = FLinearColor(1.f, 0.1f, 0.1f);
		}
		BodyMaterial->SetVectorParameterValue(TEXT("Color"), Tint);
	}

	if (PackMaterial)
	{
		Pack->SetVisibility(!bDead && CarriedAmount > 0);
		PackMaterial->SetVectorParameterValue(TEXT("Color"), ResourceColor(CarriedType));
		Pack->SetRelativeScale3D(FVector(0.25f, 0.45f, 0.3f + 0.08f * CarriedAmount));
	}

	if (const ASurvivalGameState* State = GetWorld() ? GetWorld()->GetGameState<ASurvivalGameState>() : nullptr)
	{
		// Better weapons are bigger weapons.
		Weapon->SetRelativeScale3D(FVector(0.08f + 0.02f * State->WeaponLevel, 0.08f + 0.02f * State->WeaponLevel, 0.8f + 0.08f * State->WeaponLevel));
	}
}
