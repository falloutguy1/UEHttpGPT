#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameStateBase.h"
#include "SurvivalTypes.h"
#include "SurvivalGameState.generated.h"

class AArenaProp;
class AResourceNode;
class ASafehouse;
class ASurvivorCharacter;
class AZombieCharacter;

DECLARE_MULTICAST_DELEGATE(FSurvivalClockEvent);

/** The shared world state every survivor reads: the clock, the camp stockpile, the squad plan and the event log. */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivalGameState : public AGameStateBase
{
	GENERATED_BODY()

public:
	ASurvivalGameState();

	virtual void Tick(float DeltaSeconds) override;

	// --- Clock -------------------------------------------------------------------------------

	/** Game seconds in one full day/night cycle. */
	UPROPERTY(EditAnywhere, Category = "Survival")
	float DayLength = 240.f;

	/** Fraction of the cycle at which night falls. */
	UPROPERTY(EditAnywhere, Category = "Survival")
	float NightStart = 0.68f;

	/** Surviving until dawn after this day wins the game. */
	UPROPERTY(EditAnywhere, Category = "Survival")
	int32 DaysToSurvive = 5;

	int32 Day = 1;
	float DayFraction = 0.08f;

	bool IsNight() const { return DayFraction >= NightStart; }
	float SecondsUntilNight() const { return IsNight() ? 0.f : (NightStart - DayFraction) * DayLength; }
	float SecondsUntilDawn() const { return (1.f - DayFraction) * DayLength; }

	/** 0 for most of the day, ramping to 1 as dusk arrives and staying 1 through the night. */
	float GetNightUrgency() const;

	FSurvivalClockEvent OnNightfall;
	FSurvivalClockEvent OnDawn;

	// --- Camp --------------------------------------------------------------------------------

	int32 Food = 6;
	int32 Wood = 4;
	int32 Scrap = 0;
	int32 WeaponLevel = 0;
	static constexpr int32 MaxWeaponLevel = 5;
	static constexpr int32 ScrapPerUpgrade = 5;

	float BarricadeHealth = 100.f;
	float MaxBarricadeHealth = 200.f;

	int32 ZombiesKilled = 0;

	void AddResource(EResourceType Type, int32 Amount);
	int32 GetResource(EResourceType Type) const;
	void DamageBarricade(float Amount);

	// --- Squad -------------------------------------------------------------------------------

	ESquadDirective Directive = ESquadDirective::Balanced;
	FString LeaderThought;
	FString BrainMode = TEXT("rule-based");

	void SetDirective(ESquadDirective NewDirective);

	ASurvivorCharacter* GetLeader() const;

	/** Makes sure a living survivor leads; promotes the best candidate if the leader fell. */
	void EnsureLeader();

	TArray<ASurvivorCharacter*> GetLivingSurvivors() const;

	/** True when another survivor is already working on Target (a node, a downed ally...). */
	bool IsClaimedByOther(const AActor* Target, const ASurvivorCharacter* Asker) const;

	// --- Game end ----------------------------------------------------------------------------

	bool bGameOver = false;
	bool bVictory = false;

	// --- Log ---------------------------------------------------------------------------------

	TArray<FSurvivalLogEntry> Log;
	void AddLog(const FString& Text, const FLinearColor& Color = FLinearColor::White);

	// --- World registry (filled by the game mode) --------------------------------------------

	UPROPERTY()
	TObjectPtr<ASafehouse> Safehouse;

	UPROPERTY()
	TArray<TObjectPtr<ASurvivorCharacter>> Survivors;

	UPROPERTY()
	TArray<TObjectPtr<AZombieCharacter>> Zombies;

	UPROPERTY()
	TArray<TObjectPtr<AResourceNode>> Nodes;

	UPROPERTY()
	TArray<TObjectPtr<AArenaProp>> Obstacles;

	/** Half-width of the playable square, centred on the camp. */
	float ArenaHalfSize = 4500.f;
};
