#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SurvivalTypes.h"
#include "ResourceNode.generated.h"

class UStaticMeshComponent;
class UTextRenderComponent;

/** A berry patch, a stand of trees or a wreck to strip for scrap. Slowly replenishes. */
UCLASS()
class SURVIVORSPECTATOR_API AResourceNode : public AActor
{
	GENERATED_BODY()

public:
	AResourceNode();

	void Setup(EResourceType InType, int32 InMaxAmount);

	/** Removes one unit. Returns false when the node is empty. */
	bool TakeOne();

	bool HasResources() const { return Amount > 0; }
	EResourceType GetResourceType() const { return Type; }
	int32 GetAmount() const { return Amount; }

	virtual void Tick(float DeltaSeconds) override;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Base;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Top;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UTextRenderComponent> Label;

private:
	void RefreshVisuals();

	EResourceType Type = EResourceType::None;
	int32 Amount = 0;
	int32 MaxAmount = 0;
	float RegrowTimer = 0.f;

	/** Seconds of game time to regrow one unit. */
	static constexpr float RegrowInterval = 18.f;
};
