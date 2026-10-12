#include "SurvivalSpectatorPawn.h"

#include "Camera/CameraComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/SpringArmComponent.h"
#include "Misc/App.h"

ASurvivalSpectatorPawn::ASurvivalSpectatorPawn()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bTickEvenWhenPaused = true;

	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));

	Arm = CreateDefaultSubobject<USpringArmComponent>(TEXT("Arm"));
	Arm->SetupAttachment(RootComponent);
	Arm->bUsePawnControlRotation = true;
	Arm->bDoCollisionTest = false;
	Arm->TargetArmLength = FollowDistance;

	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(Arm);
	Camera->SetFieldOfView(75.f);

	SetActorEnableCollision(false);
}

void ASurvivalSpectatorPawn::SetMode(ESpectateMode NewMode)
{
	Mode = NewMode;
	if (Mode == ESpectateMode::Tactical)
	{
		if (AController* PC = GetController())
		{
			PC->SetControlRotation(FRotator(-65.f, PC->GetControlRotation().Yaw, 0.f));
		}
	}
	else if (Mode == ESpectateMode::Free && FollowTarget.IsValid())
	{
		// Start flying from where the camera currently is.
		SetActorLocation(Camera->GetComponentLocation());
	}
}

void ASurvivalSpectatorPawn::Zoom(float Amount)
{
	if (Mode == ESpectateMode::Tactical)
	{
		TacticalDistance = FMath::Clamp(TacticalDistance + Amount * 4.f, 1500.f, 8000.f);
	}
	else
	{
		FollowDistance = FMath::Clamp(FollowDistance + Amount, 250.f, 2500.f);
	}
}

void ASurvivalSpectatorPawn::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	// Real (undilated) frame time, so the camera keeps working at any game speed.
	const float RealDelta = FMath::Min(static_cast<float>(FApp::GetDeltaTime()), 0.1f);

	switch (Mode)
	{
	case ESpectateMode::Follow:
	{
		const FVector Goal = FollowTarget.IsValid() ? FollowTarget->GetActorLocation() + FVector(0, 0, 60) : GetActorLocation();
		SetActorLocation(FMath::VInterpTo(GetActorLocation(), Goal, RealDelta, 6.f));
		Arm->TargetArmLength = FMath::FInterpTo(Arm->TargetArmLength, FollowDistance, RealDelta, 6.f);
		break;
	}
	case ESpectateMode::Tactical:
	{
		const FVector Goal = FollowTarget.IsValid() ? FollowTarget->GetActorLocation() : FVector::ZeroVector;
		SetActorLocation(FMath::VInterpTo(GetActorLocation(), FVector(Goal.X, Goal.Y, 0.f), RealDelta, 3.f));
		Arm->TargetArmLength = FMath::FInterpTo(Arm->TargetArmLength, TacticalDistance, RealDelta, 4.f);
		break;
	}
	case ESpectateMode::Free:
	{
		Arm->TargetArmLength = FMath::FInterpTo(Arm->TargetArmLength, 0.f, RealDelta, 8.f);
		const FRotator View = GetControlRotation();
		const FVector Move = FRotationMatrix(View).GetUnitAxis(EAxis::X) * FlyInput.X + FRotationMatrix(View).GetUnitAxis(EAxis::Y) * FlyInput.Y +
			FVector::UpVector * FlyInput.Z;
		AddActorWorldOffset(Move.GetClampedToMaxSize(1.f) * (bFastFly ? 3000.f : 1100.f) * RealDelta);
		break;
	}
	}
}
