#include "ArenaProp.h"

#include "Components/StaticMeshComponent.h"
#include "SurvivalAssets.h"

AArenaProp::AArenaProp()
{
	PrimaryActorTick.bCanEverTick = false;

	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	Mesh->SetMobility(EComponentMobility::Movable);
	RootComponent = Mesh;
}

void AArenaProp::Setup(UStaticMesh* InMesh, const FVector& Scale, const FLinearColor& Color, bool bBlocksMovement)
{
	Mesh->SetStaticMesh(InMesh);
	Mesh->SetWorldScale3D(Scale);
	SurvivalAssets::Paint(Mesh, Color);

	bBlocking = bBlocksMovement;
	Mesh->SetCollisionProfileName(bBlocksMovement ? TEXT("BlockAll") : TEXT("NoCollision"));

	// Basic shapes are 100 units across, so the footprint is half the larger horizontal scale.
	AvoidanceRadius = 50.f * FMath::Max(Scale.X, Scale.Y);
}
