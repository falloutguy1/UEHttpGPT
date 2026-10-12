#include "ZombieCharacter.h"

#include "AIController.h"
#include "Components/CapsuleComponent.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Safehouse.h"
#include "SurvivalAssets.h"
#include "SurvivalGameState.h"
#include "SurvivalSteering.h"
#include "SurvivorCharacter.h"

namespace
{
	const FLinearColor ZombieSkin(0.25f, 0.35f, 0.2f);
	constexpr float AttackRange = 130.f;
	constexpr float BarricadeReach = 90.f;
}

AZombieCharacter::AZombieCharacter()
{
	PrimaryActorTick.bCanEverTick = true;

	AIControllerClass = AAIController::StaticClass();
	AutoPossessAI = EAutoPossessAI::PlacedInWorldOrSpawned;

	bUseControllerRotationYaw = false;
	GetCharacterMovement()->bOrientRotationToMovement = true;
	GetCharacterMovement()->RotationRate = FRotator(0, 300, 0);
	GetCharacterMovement()->MaxWalkSpeed = 260.f;

	Body = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Body"));
	Body->SetupAttachment(GetCapsuleComponent());
	Body->SetCollisionProfileName(TEXT("NoCollision"));
	Body->SetRelativeLocation(FVector(0, 0, -20));
	Body->SetRelativeRotation(FRotator(-12, 0, 0));
	Body->SetRelativeScale3D(FVector(0.6f, 0.6f, 1.3f));

	Head = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Head"));
	Head->SetupAttachment(GetCapsuleComponent());
	Head->SetCollisionProfileName(TEXT("NoCollision"));
	Head->SetRelativeLocation(FVector(18, 0, 60));
	Head->SetRelativeScale3D(FVector(0.45f));

	// Classic outstretched arms.
	Arms = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Arms"));
	Arms->SetupAttachment(GetCapsuleComponent());
	Arms->SetCollisionProfileName(TEXT("NoCollision"));
	Arms->SetRelativeLocation(FVector(45, 0, 30));
	Arms->SetRelativeScale3D(FVector(0.8f, 0.7f, 0.12f));
}

void AZombieCharacter::InitZombie(int32 Day, bool bNightWave)
{
	MaxHealth = 50.f + 12.f * Day;
	Health = MaxHealth;
	Damage = 7.f + 1.5f * Day;
	bNight = bNightWave;
	GetCharacterMovement()->MaxWalkSpeed = (bNightWave ? 300.f : 240.f) + FMath::FRandRange(-30.f, 30.f) + 5.f * Day;
}

void AZombieCharacter::BeginPlay()
{
	Super::BeginPlay();

	Body->SetStaticMesh(SurvivalAssets::Cylinder());
	Head->SetStaticMesh(SurvivalAssets::Sphere());
	Arms->SetStaticMesh(SurvivalAssets::Cube());

	BodyMaterial = SurvivalAssets::Paint(Body, FLinearColor(0.2f, 0.18f, 0.15f));
	SurvivalAssets::Paint(Head, ZombieSkin);
	SurvivalAssets::Paint(Arms, ZombieSkin);

	WanderGoal = GetActorLocation();
}

void AZombieCharacter::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (bDead)
	{
		return;
	}

	AttackCooldown = FMath::Max(0.f, AttackCooldown - DeltaSeconds);
	HitFlash = FMath::Max(0.f, HitFlash - DeltaSeconds);
	if (BodyMaterial)
	{
		BodyMaterial->SetVectorParameterValue(TEXT("Color"), HitFlash > 0.f ? FLinearColor(1.f, 0.2f, 0.2f) : FLinearColor(0.2f, 0.18f, 0.15f));
	}

	ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>();
	if (!State || State->bGameOver)
	{
		return;
	}
	const ASafehouse* Camp = State->Safehouse;

	RetargetTimer -= DeltaSeconds;
	if (RetargetTimer <= 0.f || !Target.IsValid() || !Target->CanAct())
	{
		RetargetTimer = 1.f;
		Target = FindTarget();
	}

	ASurvivorCharacter* Victim = Target.Get();
	if (!Victim)
	{
		// Nothing in sight: drift, drawn toward the firelight at night.
		if (FVector::Dist2D(GetActorLocation(), WanderGoal) < 150.f)
		{
			const FVector Centre = (State->IsNight() && Camp) ? Camp->GetActorLocation() : GetActorLocation();
			WanderGoal = Centre + FVector(FMath::FRandRange(-1200.f, 1200.f), FMath::FRandRange(-1200.f, 1200.f), 0.f);
		}
		SurvivalSteering::MoveTowards(this, WanderGoal, 100.f);
		return;
	}

	// Survivors inside an intact barricade can only be reached by breaking through it.
	const bool bVictimSheltered = Camp && State->BarricadeHealth > 0.f && Camp->IsInside(Victim->GetActorLocation());
	if (bVictimSheltered && !Camp->IsInside(GetActorLocation()))
	{
		const FVector Breach = Camp->GetRingPoint(GetActorLocation(), 60.f);
		if (SurvivalSteering::MoveTowards(this, Breach, BarricadeReach))
		{
			SetActorRotation(FRotator(0, (Camp->GetActorLocation() - GetActorLocation()).Rotation().Yaw, 0));
			if (AttackCooldown <= 0.f)
			{
				AttackCooldown = 1.4f;
				State->DamageBarricade(Damage * 0.8f);
			}
		}
		return;
	}

	if (SurvivalSteering::MoveTowards(this, Victim->GetActorLocation(), AttackRange * 0.8f) ||
		FVector::Dist2D(GetActorLocation(), Victim->GetActorLocation()) < AttackRange)
	{
		SetActorRotation(FRotator(0, (Victim->GetActorLocation() - GetActorLocation()).Rotation().Yaw, 0));
		if (AttackCooldown <= 0.f)
		{
			AttackCooldown = 1.2f;
			Victim->ReceiveHit(Damage, this);
		}
	}
}

ASurvivorCharacter* AZombieCharacter::FindTarget() const
{
	const ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>();
	if (!State)
	{
		return nullptr;
	}

	// At night the horde can smell everyone; by day they only notice what's close.
	const float SenseRange = State->IsNight() ? 100000.f : 1600.f;
	ASurvivorCharacter* Best = nullptr;
	float BestDist = SenseRange;
	for (ASurvivorCharacter* Survivor : State->Survivors)
	{
		if (Survivor && Survivor->CanAct())
		{
			const float Dist = FVector::Dist2D(GetActorLocation(), Survivor->GetActorLocation());
			if (Dist < BestDist)
			{
				BestDist = Dist;
				Best = Survivor;
			}
		}
	}
	return Best;
}

void AZombieCharacter::ReceiveHit(float InDamage, AActor* Attacker)
{
	if (bDead)
	{
		return;
	}

	Health -= InDamage;
	HitFlash = 0.15f;

	// Knockback sells the hit.
	if (Attacker)
	{
		LaunchCharacter((GetActorLocation() - Attacker->GetActorLocation()).GetSafeNormal2D() * 250.f + FVector(0, 0, 80), true, false);
	}

	// Whoever hits us becomes the new target.
	if (ASurvivorCharacter* Survivor = Cast<ASurvivorCharacter>(Attacker))
	{
		Target = Survivor;
		RetargetTimer = 2.f;
	}

	if (Health <= 0.f)
	{
		Die(Attacker);
	}
}

void AZombieCharacter::Die(AActor* Killer)
{
	bDead = true;
	if (ASurvivalGameState* State = GetWorld()->GetGameState<ASurvivalGameState>())
	{
		++State->ZombiesKilled;
		State->Zombies.Remove(this);
		if (const ASurvivorCharacter* Survivor = Cast<ASurvivorCharacter>(Killer))
		{
			// Only log some kills so the feed isn't flooded during night waves.
			if (FMath::FRand() < 0.35f)
			{
				State->AddLog(FString::Printf(TEXT("%s dropped a zombie."), *Survivor->SurvivorName), FLinearColor(0.7f, 0.7f, 0.7f));
			}
		}
	}

	GetCharacterMovement()->DisableMovement();
	GetCapsuleComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->SetRelativeLocationAndRotation(FVector(0, 0, -75), FRotator(90, 0, 0));
	Head->SetRelativeLocation(FVector(70, 0, -75));
	Arms->SetVisibility(false);
	SetLifeSpan(6.f);
}
