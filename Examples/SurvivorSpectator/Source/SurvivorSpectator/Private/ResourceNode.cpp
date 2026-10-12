#include "ResourceNode.h"

#include "Camera/PlayerCameraManager.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextRenderComponent.h"
#include "GameFramework/PlayerController.h"
#include "SurvivalAssets.h"

AResourceNode::AResourceNode()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickInterval = 0.5f;

	Base = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Base"));
	Base->SetMobility(EComponentMobility::Movable);
	Base->SetCollisionProfileName(TEXT("NoCollision"));
	RootComponent = Base;

	Top = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Top"));
	Top->SetupAttachment(Base);
	Top->SetCollisionProfileName(TEXT("NoCollision"));

	Label = CreateDefaultSubobject<UTextRenderComponent>(TEXT("Label"));
	Label->SetupAttachment(Base);
	Label->SetHorizontalAlignment(EHTA_Center);
	Label->SetWorldSize(40.f);
	Label->SetUsingAbsoluteScale(true);
}

void AResourceNode::Setup(EResourceType InType, int32 InMaxAmount)
{
	Type = InType;
	MaxAmount = InMaxAmount;
	Amount = InMaxAmount;

	switch (Type)
	{
	case EResourceType::Food: // Berry bush: green mound with red berries.
		Base->SetStaticMesh(SurvivalAssets::Sphere());
		Base->SetWorldScale3D(FVector(1.6f, 1.6f, 0.9f));
		SurvivalAssets::Paint(Base, FLinearColor(0.08f, 0.35f, 0.08f));
		Top->SetStaticMesh(SurvivalAssets::Sphere());
		Top->SetRelativeLocation(FVector(0, 0, 45));
		Top->SetRelativeScale3D(FVector(0.35f));
		SurvivalAssets::Paint(Top, FLinearColor(0.7f, 0.05f, 0.05f));
		Label->SetTextRenderColor(FColor(120, 255, 120));
		break;
	case EResourceType::Wood: // Tree: trunk and canopy.
		Base->SetStaticMesh(SurvivalAssets::Cylinder());
		Base->SetWorldScale3D(FVector(0.5f, 0.5f, 3.f));
		SurvivalAssets::Paint(Base, FLinearColor(0.25f, 0.13f, 0.05f));
		Top->SetStaticMesh(SurvivalAssets::Cone());
		Top->SetRelativeLocation(FVector(0, 0, 90));
		Top->SetRelativeScale3D(FVector(5.f, 5.f, 1.f));
		SurvivalAssets::Paint(Top, FLinearColor(0.05f, 0.22f, 0.06f));
		Label->SetTextRenderColor(FColor(230, 170, 100));
		break;
	case EResourceType::Scrap: // Wrecked car: body and cabin.
		Base->SetStaticMesh(SurvivalAssets::Cube());
		Base->SetWorldScale3D(FVector(3.6f, 1.8f, 0.9f));
		SurvivalAssets::Paint(Base, FLinearColor(0.35f, 0.12f, 0.08f));
		Top->SetStaticMesh(SurvivalAssets::Cube());
		Top->SetRelativeLocation(FVector(-10, 0, 80));
		Top->SetRelativeScale3D(FVector(0.5f, 0.9f, 0.7f));
		SurvivalAssets::Paint(Top, FLinearColor(0.2f, 0.2f, 0.22f));
		Label->SetTextRenderColor(FColor(180, 200, 255));
		break;
	default:
		break;
	}

	// Basic shapes are centred on their origin, so lift the node to sit on the ground.
	AddActorWorldOffset(FVector(0, 0, 50.f * Base->GetComponentScale().Z));
	Label->SetWorldLocation(GetActorLocation() + FVector(0, 0, Type == EResourceType::Wood ? 470.f : 160.f));
	RefreshVisuals();
}

bool AResourceNode::TakeOne()
{
	if (Amount <= 0)
	{
		return false;
	}
	--Amount;
	RefreshVisuals();
	return true;
}

void AResourceNode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (Amount < MaxAmount)
	{
		RegrowTimer += DeltaSeconds;
		if (RegrowTimer >= RegrowInterval)
		{
			RegrowTimer = 0.f;
			++Amount;
			RefreshVisuals();
		}
	}

	// Keep the label readable from whichever camera is spectating.
	if (const APlayerController* PC = GetWorld()->GetFirstPlayerController())
	{
		if (PC->PlayerCameraManager)
		{
			const FVector ToCamera = PC->PlayerCameraManager->GetCameraLocation() - Label->GetComponentLocation();
			Label->SetWorldRotation(FRotator(0, ToCamera.Rotation().Yaw, 0));
		}
	}
}

void AResourceNode::RefreshVisuals()
{
	const FString Name = SurvivalNames::ResourceName(Type);
	Label->SetText(FText::FromString(FString::Printf(TEXT("%s %d/%d"), *Name.ToUpper(), Amount, MaxAmount)));
	Top->SetVisibility(Amount > 0);
}
