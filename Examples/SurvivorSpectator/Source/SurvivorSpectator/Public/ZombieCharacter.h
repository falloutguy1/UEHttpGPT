#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"
#include "ZombieCharacter.generated.h"

class ASurvivorCharacter;
class UMaterialInstanceDynamic;
class UStaticMeshComponent;

/** Shambles toward the nearest survivor. At camp it has to tear through the barricade first. */
UCLASS()
class SURVIVORSPECTATOR_API AZombieCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AZombieCharacter();

	/** Scales toughness with the day number. */
	void InitZombie(int32 Day, bool bNightWave);

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	void ReceiveHit(float Damage, AActor* Attacker);
	bool IsDead() const { return bDead; }

	float Health = 60.f;
	float MaxHealth = 60.f;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Body;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Head;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UStaticMeshComponent> Arms;

private:
	ASurvivorCharacter* FindTarget() const;
	void Die(AActor* Killer);

	TWeakObjectPtr<ASurvivorCharacter> Target;
	FVector WanderGoal = FVector::ZeroVector;
	float RetargetTimer = 0.f;
	float AttackCooldown = 0.f;
	float HitFlash = 0.f;
	float Damage = 8.f;
	bool bNight = false;
	bool bDead = false;

	UPROPERTY()
	TObjectPtr<UMaterialInstanceDynamic> BodyMaterial;
};
