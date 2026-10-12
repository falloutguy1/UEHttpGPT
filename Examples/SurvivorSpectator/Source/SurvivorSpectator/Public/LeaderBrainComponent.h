#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "SurvivalTypes.h"
#include "Structures/HttpGPTChatTypes.h"
#include "LeaderBrainComponent.generated.h"

class ASurvivalGameState;
class ASurvivorCharacter;
class UHttpGPTChatRequest;

/**
 * The squad leader's strategic mind. Every so often (and whenever something dramatic happens) it reads
 * the situation and picks a squad directive, says something to the team and has a private thought the
 * spectator can read.
 *
 * With an OpenAI key set in Project Settings > Plugins > HttpGPT it thinks with GPT through the HttpGPT
 * plugin. Without one, or if a request fails, it falls back to a rule-based planner.
 */
UCLASS(ClassGroup = (Survival), meta = (BlueprintSpawnableComponent))
class SURVIVORSPECTATOR_API ULeaderBrainComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	ULeaderBrainComponent();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	/** Asks for a fresh plan soon because of Reason (an ally went down, night fell...). */
	void RequestThink(const FString& Reason);

	/** Seconds of game time between routine planning sessions. */
	UPROPERTY(EditAnywhere, Category = "Survival")
	float ThinkInterval = 22.f;

	/** Never think more often than this, even when events pile up. */
	UPROPERTY(EditAnywhere, Category = "Survival")
	float MinThinkGap = 7.f;

private:
	void Think();
	void ThinkWithRules();
	bool ThinkWithGPT();
	void HandleFailure();
	void Apply(ESquadDirective Directive, const FString& Say, const FString& Thought);

	FString DescribeSituation() const;

	UFUNCTION()
	void OnGPTCompleted(const FHttpGPTChatResponse& Response);

	UFUNCTION()
	void OnGPTFailed(const FHttpGPTChatResponse& Response);

	UFUNCTION()
	void OnGPTRequestFailed();

	ASurvivorCharacter* Owner() const;
	ASurvivalGameState* State() const;

	float SinceThink = 15.f;
	TArray<FString> PendingReasons;
	bool bRequestInFlight = false;
	int32 GPTFailures = 0;
	bool bSpeakOnApply = false;

	UPROPERTY()
	TObjectPtr<UHttpGPTChatRequest> ActiveRequest;
};
