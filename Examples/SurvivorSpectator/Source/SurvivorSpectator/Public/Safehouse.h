#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Safehouse.generated.h"

class UPointLightComponent;
class UStaticMeshComponent;

/** The squad's camp: a campfire inside a ring of barricade posts. The posts thin out as the barricade is damaged. */
UCLASS()
class SURVIVORSPECTATOR_API ASafehouse : public AActor
{
	GENERATED_BODY()

public:
	ASafehouse();

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	/** Radius of the barricade ring. Survivors inside it are "at camp". */
	UPROPERTY(EditAnywhere, Category = "Survival")
	float Radius = 650.f;

	bool IsInside(const FVector& Location, float Margin = 0.f) const;

	/** A point on the barricade ring facing From, offset outward by Offset. */
	FVector GetRingPoint(const FVector& From, float Offset = 0.f) const;

	/** A random spot near the campfire. */
	FVector GetRandomCampSpot() const;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Fire;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UPointLightComponent> FireLight;

private:
	UPROPERTY()
	TArray<TObjectPtr<UStaticMeshComponent>> Posts;

	float FlickerTime = 0.f;
};
