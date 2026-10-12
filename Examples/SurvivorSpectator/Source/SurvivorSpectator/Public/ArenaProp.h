#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "ArenaProp.generated.h"

class UStaticMeshComponent;

/** A runtime-spawned piece of scenery: ground, rocks, wrecked cars, fence posts. */
UCLASS()
class SURVIVORSPECTATOR_API AArenaProp : public AActor
{
	GENERATED_BODY()

public:
	AArenaProp();

	void Setup(UStaticMesh* Mesh, const FVector& Scale, const FLinearColor& Color, bool bBlocksMovement);

	/** Rough footprint radius used by the steering code to walk around blocking props. */
	float GetAvoidanceRadius() const { return AvoidanceRadius; }
	bool BlocksMovement() const { return bBlocking; }

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Mesh;

private:
	float AvoidanceRadius = 0.f;
	bool bBlocking = false;
};
