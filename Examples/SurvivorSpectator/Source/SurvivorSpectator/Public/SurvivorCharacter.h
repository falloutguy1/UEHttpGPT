#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "SurvivalTypes.h"
#include "SurvivorCharacter.generated.h"

class ULeaderBrainComponent;
class UMaterialInstanceDynamic;
class UStaticMeshComponent;
class AZombieCharacter;

/** An AI-controlled survivor. Its needs and personality feed the utility scoring in ASurvivorAIController. */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivorCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	ASurvivorCharacter();

	void InitSurvivor(const FString& InName, const FLinearColor& InColor, float InBravery, float InCooperation, float InDiligence,
	                  EResourceType InFavourite, bool bInLeader);

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	// --- Identity & personality ----------------------------------------------------------------

	FString SurvivorName;
	FLinearColor Color = FLinearColor::White;
	bool bIsLeader = false;

	/** Willingness to fight rather than run. */
	float Bravery = 0.5f;
	/** Willingness to drop their own work to help others. */
	float Cooperation = 0.5f;
	/** Work speed and appetite for chores. */
	float Diligence = 0.5f;
	EResourceType Favourite = EResourceType::None;

	// --- Needs -------------------------------------------------------------------------------

	float Health = 100.f;
	float MaxHealth = 100.f;
	/** 100 = full, 0 = starving. */
	float Fullness = 85.f;
	float Stamina = 100.f;

	bool IsDowned() const { return bDowned; }
	bool IsDead() const { return bDead; }
	bool CanAct() const { return !bDowned && !bDead; }
	float GetBleedOut() const { return BleedOut; }

	// --- Inventory ---------------------------------------------------------------------------

	EResourceType CarriedType = EResourceType::None;
	int32 CarriedAmount = 0;
	static constexpr int32 MaxCarry = 5;

	void AddCarried(EResourceType Type);
	void ClearCarried();

	// --- Actions -----------------------------------------------------------------------------

	/** Swings at a zombie if the attack is off cooldown. Returns true if a hit landed. */
	bool TryAttack(AZombieCharacter* Target);

	void ReceiveHit(float Damage, AActor* Attacker);
	void Revive(ASurvivorCharacter* Rescuer);

	/** Speech shown above the head and recorded in the event log. */
	void Say(const FString& Line, float Duration = 4.f);
	const FString& GetSpeech() const { return Speech; }

	/** Set true while sprinting (fleeing). Drains stamina. */
	void SetSprinting(bool bSprint);

	/** Seconds since this survivor last took damage. */
	float TimeSinceHurt() const;

	/** The zombie that last hurt this survivor, if it is still around. */
	TWeakObjectPtr<AZombieCharacter> LastAttacker;

	/** The node, ally or zombie this survivor is working on. Others avoid duplicating the work. */
	TWeakObjectPtr<AActor> ClaimedTarget;

	/** For the HUD. */
	ESurvivorTask CurrentTask = ESurvivorTask::Idle;
	FString TaskDetail;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Body;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Head;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Pack;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Weapon;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<ULeaderBrainComponent> LeaderBrain;

private:
	void GoDown();
	void Die();
	void RefreshLook();

	bool bDowned = false;
	bool bDead = false;
	bool bSprinting = false;
	float BleedOut = 0.f;
	float AttackCooldown = 0.f;
	float HitFlash = 0.f;
	float LastHurtTime = -100.f;
	float LastHelpCallTime = -100.f;

	FString Speech;
	float SpeechTimer = 0.f;

	UPROPERTY()
	TObjectPtr<UMaterialInstanceDynamic> BodyMaterial;

	UPROPERTY()
	TObjectPtr<UMaterialInstanceDynamic> PackMaterial;
};
