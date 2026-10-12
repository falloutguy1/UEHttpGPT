#pragma once

#include "CoreMinimal.h"
#include "AIController.h"
#include "SurvivalTypes.h"
#include "SurvivorAIController.generated.h"

class AResourceNode;
class ASurvivalGameState;
class ASurvivorCharacter;
class AZombieCharacter;

/**
 * Utility AI for one survivor. Every half second it scores each possible task from the survivor's needs,
 * personality, the camp's stockpile, the time of day, what teammates are already doing, and the
 * leader's directive, then works on the best one.
 */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivorAIController : public AAIController
{
	GENERATED_BODY()

public:
	ASurvivorAIController();

	virtual void Tick(float DeltaSeconds) override;

private:
	struct FOption
	{
		ESurvivorTask Task = ESurvivorTask::Idle;
		float Score = 0.f;
		TWeakObjectPtr<AActor> Target;
		EResourceType Resource = EResourceType::None;
	};

	void Decide();
	void Execute(float DeltaSeconds);
	void SwitchTo(const FOption& Option);

	void ScoreOptions(TArray<FOption>& Out) const;
	float DirectiveBonus(ESurvivorTask Task, EResourceType Resource) const;

	AZombieCharacter* NearestZombie(const FVector& From, float MaxDist) const;
	/** A zombie hurting a teammate within reach, preferring the most endangered teammate. */
	AZombieCharacter* ZombieThreateningAlly(float& OutUrgency) const;
	ASurvivorCharacter* DownedAllyToSave(float& OutUrgency) const;
	AResourceNode* BestNode(EResourceType Type, float& OutDistance) const;
	float ResourceNeed(EResourceType Type) const;
	bool IsAtCamp(float Margin = 0.f) const;

	void SayOnce(const FString& Line, float Cooldown = 10.f);

	ASurvivorCharacter* Me() const;
	ASurvivalGameState* State() const;

	FOption Current;
	float DecideTimer = 0.f;
	float WorkTimer = 0.f;
	float LastLineTime = -100.f;
	bool bNeedsNewTask = true;
	FVector IdleSpot = FVector::ZeroVector;
};
