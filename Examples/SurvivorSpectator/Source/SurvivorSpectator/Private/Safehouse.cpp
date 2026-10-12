#include "Safehouse.h"

#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "SurvivalAssets.h"
#include "SurvivalGameState.h"

ASafehouse::ASafehouse()
{
	PrimaryActorTick.bCanEverTick = true;

	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	RootComponent = Root;

	Fire = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Fire"));
	Fire->SetupAttachment(Root);
	Fire->SetCollisionProfileName(TEXT("NoCollision"));
	Fire->SetRelativeLocation(FVector(0, 0, 40));
	Fire->SetRelativeScale3D(FVector(0.8f, 0.8f, 0.8f));

	FireLight = CreateDefaultSubobject<UPointLightComponent>(TEXT("FireLight"));
	FireLight->SetupAttachment(Root);
	FireLight->SetRelativeLocation(FVector(0, 0, 150));
	FireLight->IntensityUnits = ELightUnits::Candelas;
	FireLight->Intensity = 60.f;
	FireLight->AttenuationRadius = 1600.f;
	FireLight->SetLightColor(FLinearColor(1.f, 0.55f, 0.2f));
}

void ASafehouse::BeginPlay()
{
	Super::BeginPlay();

	Fire->SetStaticMesh(SurvivalAssets::Cone());
	SurvivalAssets::Paint(Fire, FLinearColor(1.f, 0.35f, 0.05f));

	// Logs around the fire and a few tents give the camp some shape.
	for (int32 i = 0; i < 3; ++i)
	{
		UStaticMeshComponent* Tent = NewObject<UStaticMeshComponent>(this);
		Tent->SetupAttachment(Root);
		Tent->SetCollisionProfileName(TEXT("NoCollision"));
		Tent->RegisterComponent();
		Tent->SetStaticMesh(SurvivalAssets::Cone());
		const float Angle = FMath::DegreesToRadians(40.f + i * 120.f);
		Tent->SetRelativeLocation(FVector(FMath::Cos(Angle) * 380.f, FMath::Sin(Angle) * 380.f, 80.f));
		Tent->SetRelativeScale3D(FVector(2.2f, 2.2f, 1.6f));
		SurvivalAssets::Paint(Tent, FLinearColor(0.15f + 0.1f * i, 0.25f, 0.15f));
	}

	// Barricade ring. Purely visual: the barricade's strength lives in the game state.
	constexpr int32 PostCount = 28;
	for (int32 i = 0; i < PostCount; ++i)
	{
		UStaticMeshComponent* Post = NewObject<UStaticMeshComponent>(this);
		Post->SetupAttachment(Root);
		Post->SetCollisionProfileName(TEXT("NoCollision"));
		Post->RegisterComponent();
		Post->SetStaticMesh(SurvivalAssets::Cube());
		const float Angle = 2.f * PI * i / PostCount;
		Post->SetRelativeLocation(FVector(FMath::Cos(Angle) * Radius, FMath::Sin(Angle) * Radius, 70.f));
		Post->SetRelativeRotation(FRotator(FMath::RandRange(-8.f, 8.f), FMath::RadiansToDegrees(Angle), FMath::RandRange(-10.f, 10.f)));
		Post->SetRelativeScale3D(FVector(0.25f, 1.4f, 1.4f));
		SurvivalAssets::Paint(Post, FLinearColor(0.3f, 0.18f, 0.08f));
		Posts.Add(Post);
	}
}

void ASafehouse::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	FlickerTime += DeltaSeconds;
	const float Flicker = 0.85f + 0.15f * FMath::Sin(FlickerTime * 13.f) * FMath::Sin(FlickerTime * 7.3f);
	FireLight->SetIntensity(60.f * Flicker);

	if (const ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		// Show as many posts as the barricade's health allows, spread evenly around the ring.
		const float Ratio = State->BarricadeHealth / State->MaxBarricadeHealth;
		for (int32 i = 0; i < Posts.Num(); ++i)
		{
			const float Threshold = static_cast<float>((i * 11) % Posts.Num()) / Posts.Num();
			Posts[i]->SetVisibility(Ratio > Threshold);
		}
	}
}

bool ASafehouse::IsInside(const FVector& Location, float Margin) const
{
	return FVector::Dist2D(Location, GetActorLocation()) < Radius + Margin;
}

FVector ASafehouse::GetRingPoint(const FVector& From, float Offset) const
{
	FVector Dir = (From - GetActorLocation()).GetSafeNormal2D();
	if (Dir.IsNearlyZero())
	{
		Dir = FVector::ForwardVector;
	}
	return GetActorLocation() + Dir * (Radius + Offset);
}

FVector ASafehouse::GetRandomCampSpot() const
{
	const float Angle = FMath::FRandRange(0.f, 2.f * PI);
	const float Dist = FMath::FRandRange(150.f, Radius * 0.6f);
	return GetActorLocation() + FVector(FMath::Cos(Angle) * Dist, FMath::Sin(Angle) * Dist, 0.f);
}
