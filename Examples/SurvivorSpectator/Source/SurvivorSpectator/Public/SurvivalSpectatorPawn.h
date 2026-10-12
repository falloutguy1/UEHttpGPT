#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"
#include "SurvivalSpectatorPawn.generated.h"

class UCameraComponent;
class USpringArmComponent;

UENUM()
enum class ESpectateMode : uint8
{
	/** Orbit camera locked onto one survivor. */
	Follow,
	/** High overview of the whole camp. */
	Tactical,
	/** Fly anywhere. */
	Free
};

/**
 * The player's eyes. The player never controls a survivor: they only watch.
 * Camera smoothing uses real time so it stays responsive when the game is slowed down or paused.
 */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivalSpectatorPawn : public APawn
{
	GENERATED_BODY()

public:
	ASurvivalSpectatorPawn();

	virtual void Tick(float DeltaSeconds) override;

	void SetMode(ESpectateMode NewMode);
	ESpectateMode GetMode() const { return Mode; }

	void SetFollowTarget(AActor* Target) { FollowTarget = Target; }
	AActor* GetFollowTarget() const { return FollowTarget.Get(); }

	void Zoom(float Amount);

	/** Free-camera fly input, -1..1 per axis. */
	FVector FlyInput = FVector::ZeroVector;
	bool bFastFly = false;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USpringArmComponent> Arm;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UCameraComponent> Camera;

private:
	ESpectateMode Mode = ESpectateMode::Follow;
	TWeakObjectPtr<AActor> FollowTarget;
	float FollowDistance = 650.f;
	float TacticalDistance = 3800.f;
};
