#include "SurvivorAIController.h"

#include "ResourceNode.h"
#include "Safehouse.h"
#include "SurvivalGameState.h"
#include "SurvivalSteering.h"
#include "SurvivorCharacter.h"
#include "ZombieCharacter.h"

namespace
{
	constexpr float MeleeRange = 140.f;
	constexpr float WorkRange = 190.f;
	constexpr float DecideInterval = 0.4f;
	/** Bonus for sticking with the current task so survivors don't dither between close scores. */
	constexpr float Commitment = 0.12f;
}

ASurvivorAIController::ASurvivorAIController()
{
	PrimaryActorTick.bCanEverTick = true;
}

ASurvivorCharacter* ASurvivorAIController::Me() const
{
	return Cast<ASurvivorCharacter>(GetPawn());
}

ASurvivalGameState* ASurvivorAIController::State() const
{
	return GetWorld()->GetGameState<ASurvivalGameState>();
}

void ASurvivorAIController::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	ASurvivorCharacter* Self = Me();
	ASurvivalGameState* GS = State();
	if (!Self || !GS || !GS->Safehouse)
	{
		return;
	}

	if (!Self->CanAct() || GS->bGameOver)
	{
		Self->SetSprinting(false);
		Self->CurrentTask = ESurvivorTask::Idle;
		Self->TaskDetail = Self->IsDead() ? TEXT("Dead") : (Self->IsDowned() ? TEXT("Bleeding out") : TEXT(""));
		return;
	}

	DecideTimer -= DeltaSeconds;
	if (DecideTimer <= 0.f)
	{
		DecideTimer = DecideInterval;
		Decide();
	}
	Execute(DeltaSeconds);
}

// --- Perception helpers ------------------------------------------------------------------------

AZombieCharacter* ASurvivorAIController::NearestZombie(const FVector& From, float MaxDist) const
{
	AZombieCharacter* Best = nullptr;
	float BestDist = MaxDist;
	for (AZombieCharacter* Zombie : State()->Zombies)
	{
		if (Zombie && !Zombie->IsDead())
		{
			const float Dist = FVector::Dist2D(From, Zombie->GetActorLocation());
			if (Dist < BestDist)
			{
				BestDist = Dist;
				Best = Zombie;
			}
		}
	}
	return Best;
}

AZombieCharacter* ASurvivorAIController::ZombieThreateningAlly(float& OutUrgency) const
{
	const ASurvivorCharacter* Self = Me();
	AZombieCharacter* Best = nullptr;
	OutUrgency = 0.f;

	for (const ASurvivorCharacter* Ally : State()->Survivors)
	{
		if (!Ally || Ally == Self || !Ally->CanAct())
		{
			continue;
		}
		const float AllyDist = FVector::Dist2D(Self->GetActorLocation(), Ally->GetActorLocation());
		if (AllyDist > 2200.f)
		{
			continue;
		}
		AZombieCharacter* Attacker = NearestZombie(Ally->GetActorLocation(), 350.f);
		if (!Attacker)
		{
			continue;
		}
		// Hurt, recently-hit allies close by need us most.
		const float Danger = (1.f - Ally->Health / Ally->MaxHealth) * 0.5f + (Ally->TimeSinceHurt() < 3.f ? 0.4f : 0.1f);
		const float Urgency = Danger * (1.f - AllyDist / 2200.f * 0.5f);
		if (Urgency > OutUrgency)
		{
			OutUrgency = Urgency;
			Best = Attacker;
		}
	}
	return Best;
}

ASurvivorCharacter* ASurvivorAIController::DownedAllyToSave(float& OutUrgency) const
{
	const ASurvivorCharacter* Self = Me();
	ASurvivorCharacter* Best = nullptr;
	OutUrgency = 0.f;

	for (ASurvivorCharacter* Ally : State()->Survivors)
	{
		if (!Ally || Ally == Self || !Ally->IsDowned() || State()->IsClaimedByOther(Ally, Self))
		{
			continue;
		}
		const float Dist = FVector::Dist2D(Self->GetActorLocation(), Ally->GetActorLocation());
		const float TravelTime = Dist / 450.f + 3.5f;
		if (TravelTime > Ally->GetBleedOut())
		{
			continue; // Can't make it in time.
		}
		const float Urgency = 1.f - 0.4f * (Dist / 5000.f);
		if (Urgency > OutUrgency)
		{
			OutUrgency = Urgency;
			Best = Ally;
		}
	}
	return Best;
}

AResourceNode* ASurvivorAIController::BestNode(EResourceType Type, float& OutDistance) const
{
	const ASurvivorCharacter* Self = Me();
	AResourceNode* Best = nullptr;
	float BestCost = TNumericLimits<float>::Max();

	for (AResourceNode* Node : State()->Nodes)
	{
		if (!Node || Node->GetResourceType() != Type || !Node->HasResources() || State()->IsClaimedByOther(Node, Self))
		{
			continue;
		}
		float Cost = FVector::Dist2D(Self->GetActorLocation(), Node->GetActorLocation());
		// Avoid nodes with zombies hanging around them.
		if (NearestZombie(Node->GetActorLocation(), 700.f))
		{
			Cost += 2500.f * (1.2f - Self->Bravery);
		}
		if (Cost < BestCost)
		{
			BestCost = Cost;
			Best = Node;
		}
	}

	OutDistance = Best ? FVector::Dist2D(Self->GetActorLocation(), Best->GetActorLocation()) : 0.f;
	return Best;
}

float ASurvivorAIController::ResourceNeed(EResourceType Type) const
{
	const ASurvivalGameState* GS = State();
	const int32 Mouths = FMath::Max(1, GS->GetLivingSurvivors().Num());
	switch (Type)
	{
	case EResourceType::Food: return FMath::Clamp(1.f - GS->Food / (Mouths * 3.f), 0.f, 1.f);
	case EResourceType::Wood:
	{
		// Wood is wanted both in the pile and to fill the barricade's missing health.
		const float Missing = (GS->MaxBarricadeHealth - GS->BarricadeHealth) / 15.f;
		return FMath::Clamp(1.f - (GS->Wood - Missing * 0.5f) / 15.f, 0.f, 1.f);
	}
	case EResourceType::Scrap:
		return GS->WeaponLevel >= ASurvivalGameState::MaxWeaponLevel ? 0.f : FMath::Clamp(1.f - GS->Scrap / 10.f, 0.f, 1.f) * 0.8f;
	default: return 0.f;
	}
}

bool ASurvivorAIController::IsAtCamp(float Margin) const
{
	return State()->Safehouse->IsInside(Me()->GetActorLocation(), Margin);
}

float ASurvivorAIController::DirectiveBonus(ESurvivorTask Task, EResourceType Resource) const
{
	float Bonus = 0.f;
	switch (State()->Directive)
	{
	case ESquadDirective::StockpileFood:
		Bonus = (Task == ESurvivorTask::Gather && Resource == EResourceType::Food) ? 0.3f : 0.f;
		break;
	case ESquadDirective::GatherWood:
		Bonus = (Task == ESurvivorTask::Gather && Resource == EResourceType::Wood) ? 0.3f : (Task == ESurvivorTask::Repair ? 0.1f : 0.f);
		break;
	case ESquadDirective::ScavengeScrap:
		Bonus = (Task == ESurvivorTask::Gather && Resource == EResourceType::Scrap) ? 0.3f : (Task == ESurvivorTask::Craft ? 0.2f : 0.f);
		break;
	case ESquadDirective::Fortify:
		Bonus = Task == ESurvivorTask::Repair ? 0.35f
			: (Task == ESurvivorTask::Gather && Resource == EResourceType::Wood) ? 0.15f
			: Task == ESurvivorTask::Deposit ? 0.1f : 0.f;
		break;
	case ESquadDirective::ProtectEachOther:
		Bonus = Task == ESurvivorTask::Revive ? 0.3f : Task == ESurvivorTask::Fight ? 0.2f : Task == ESurvivorTask::Gather ? -0.1f : 0.f;
		break;
	case ESquadDirective::Regroup:
		Bonus = (Task == ESurvivorTask::Defend || Task == ESurvivorTask::Idle) ? 0.35f
			: Task == ESurvivorTask::Deposit ? 0.2f
			: Task == ESurvivorTask::Gather ? -0.25f : 0.f;
		break;
	default:
		break;
	}
	// The leader holds themselves to their own plan more strongly.
	return Me()->bIsLeader ? Bonus * 1.4f : Bonus;
}

// --- Decision making ---------------------------------------------------------------------------

void ASurvivorAIController::ScoreOptions(TArray<FOption>& Out) const
{
	const ASurvivorCharacter* Self = Me();
	const ASurvivalGameState* GS = State();
	const float Urgency = GS->GetNightUrgency();
	const float HealthRatio = Self->Health / Self->MaxHealth;
	const FVector Pos = Self->GetActorLocation();

	auto Add = [&Out](ESurvivorTask Task, float Score, AActor* Target = nullptr, EResourceType Resource = EResourceType::None)
	{
		FOption& Option = Out.AddDefaulted_GetRef();
		Option.Task = Task;
		Option.Score = Score;
		Option.Target = Target;
		Option.Resource = Resource;
	};

	// Flee when badly hurt with a zombie close.
	if (AZombieCharacter* Close = NearestZombie(Pos, 500.f))
	{
		if (HealthRatio < 0.35f)
		{
			Add(ESurvivorTask::Flee, 0.95f - 0.4f * Self->Bravery + (0.35f - HealthRatio), Close);
		}
	}

	// Fight a nearby zombie, more eagerly if it's attacking us or we're well armed.
	if (AZombieCharacter* Threat = NearestZombie(Pos, 800.f))
	{
		const float Dist = FVector::Dist2D(Pos, Threat->GetActorLocation());
		const float SelfDefence = (Self->LastAttacker.Get() == Threat && Self->TimeSinceHurt() < 4.f) ? 0.3f : 0.f;
		const float Score = 0.45f + 0.35f * Self->Bravery + SelfDefence + 0.04f * GS->WeaponLevel - 0.3f * (Dist / 800.f)
			- (HealthRatio < 0.35f ? 0.4f : 0.f);
		Add(ESurvivorTask::Fight, Score + DirectiveBonus(ESurvivorTask::Fight, EResourceType::None), Threat);
	}

	// Go help a teammate who is being attacked.
	float HelpUrgency = 0.f;
	if (AZombieCharacter* AllyThreat = ZombieThreateningAlly(HelpUrgency))
	{
		const float Score = 0.3f + 0.5f * Self->Cooperation * HelpUrgency + 0.2f * Self->Bravery - (HealthRatio < 0.4f ? 0.35f : 0.f);
		Add(ESurvivorTask::Fight, Score + DirectiveBonus(ESurvivorTask::Fight, EResourceType::None), AllyThreat);
	}

	// Revive a downed teammate.
	float ReviveUrgency = 0.f;
	if (ASurvivorCharacter* Downed = DownedAllyToSave(ReviveUrgency))
	{
		const float Danger = NearestZombie(Downed->GetActorLocation(), 500.f) ? 0.25f * (1.f - Self->Bravery) : 0.f;
		const float Score = 0.55f + 0.45f * Self->Cooperation * ReviveUrgency - Danger;
		Add(ESurvivorTask::Revive, Score + DirectiveBonus(ESurvivorTask::Revive, EResourceType::None), Downed);
	}

	// Eat when hungry, from our own pack first, otherwise from the camp stockpile.
	const bool bHasFood = (Self->CarriedType == EResourceType::Food && Self->CarriedAmount > 0) || GS->Food > 0;
	if (bHasFood && Self->Fullness < 55.f)
	{
		Add(ESurvivorTask::Eat, (1.f - Self->Fullness / 55.f) * 0.9f + 0.15f);
	}

	// Rest when exhausted or hurt, mostly at night.
	if (Self->Stamina < 30.f || (HealthRatio < 0.6f && Urgency >= 1.f))
	{
		Add(ESurvivorTask::Rest, 0.25f + (1.f - Self->Stamina / 100.f) * 0.4f + (1.f - HealthRatio) * 0.3f);
	}

	// Bring back what we're carrying: when full, or when dark is coming.
	if (Self->CarriedAmount > 0)
	{
		const float Fill = static_cast<float>(Self->CarriedAmount) / ASurvivorCharacter::MaxCarry;
		Add(ESurvivorTask::Deposit, 0.2f + 0.55f * Fill + 0.4f * Urgency + DirectiveBonus(ESurvivorTask::Deposit, EResourceType::None));
	}

	// Patch the barricade.
	const float BarricadeRatio = GS->BarricadeHealth / GS->MaxBarricadeHealth;
	if (GS->Wood > 0 && BarricadeRatio < 0.95f)
	{
		const float Score = 0.15f + (1.f - BarricadeRatio) * 0.55f + 0.35f * Urgency + 0.1f * Self->Diligence;
		Add(ESurvivorTask::Repair, Score + DirectiveBonus(ESurvivorTask::Repair, EResourceType::None));
	}

	// Turn scrap into better weapons for everyone.
	if (GS->Scrap >= ASurvivalGameState::ScrapPerUpgrade && GS->WeaponLevel < ASurvivalGameState::MaxWeaponLevel)
	{
		Add(ESurvivorTask::Craft, 0.4f + 0.15f * Self->Diligence + DirectiveBonus(ESurvivorTask::Craft, EResourceType::None));
	}

	// Gather whatever the camp needs most. Venturing out gets less attractive as night approaches.
	for (EResourceType Type : {EResourceType::Food, EResourceType::Wood, EResourceType::Scrap})
	{
		if (Self->CarriedAmount >= ASurvivorCharacter::MaxCarry || (Self->CarriedAmount > 0 && Self->CarriedType != Type))
		{
			continue;
		}
		float Distance = 0.f;
		if (AResourceNode* Node = BestNode(Type, Distance))
		{
			float Score = 0.2f + 0.45f * ResourceNeed(Type) + 0.15f * Self->Diligence - 0.08f * (Distance / 3000.f);
			Score += (Type == Self->Favourite) ? 0.08f : 0.f;
			Score -= 0.7f * Urgency;
			Add(ESurvivorTask::Gather, Score + DirectiveBonus(ESurvivorTask::Gather, Type), Node, Type);
		}
	}

	// At night, hold the barricade line.
	if (GS->IsNight())
	{
		const bool bZombiesNearCamp = NearestZombie(GS->Safehouse->GetActorLocation(), GS->Safehouse->Radius + 700.f) != nullptr;
		Add(ESurvivorTask::Defend, 0.35f + (bZombiesNearCamp ? 0.25f * Self->Bravery : 0.f) + DirectiveBonus(ESurvivorTask::Defend, EResourceType::None));
	}

	Add(ESurvivorTask::Idle, 0.1f + 0.3f * Urgency + DirectiveBonus(ESurvivorTask::Idle, EResourceType::None));
}

void ASurvivorAIController::Decide()
{
	TArray<FOption> Options;
	ScoreOptions(Options);

	const FOption* Best = nullptr;
	float BestScore = -1000.f;
	for (const FOption& Option : Options)
	{
		const bool bSameAsCurrent = Option.Task == Current.Task && Option.Target == Current.Target;
		const float Score = Option.Score + (bSameAsCurrent ? Commitment : 0.f);
		if (Score > BestScore)
		{
			BestScore = Score;
			Best = &Option;
		}
	}

	if (Best && (bNeedsNewTask || !(Best->Task == Current.Task && Best->Target == Current.Target)))
	{
		bNeedsNewTask = false;
		SwitchTo(*Best);
	}
}

void ASurvivorAIController::SwitchTo(const FOption& Option)
{
	ASurvivorCharacter* Self = Me();
	const ESurvivorTask Previous = Current.Task;
	Current = Option;
	WorkTimer = 0.f;
	Self->SetSprinting(Option.Task == ESurvivorTask::Flee || Option.Task == ESurvivorTask::Revive);

	// Claims let teammates spread out over nodes and downed allies instead of all piling on one.
	const bool bClaims = Option.Task == ESurvivorTask::Gather || Option.Task == ESurvivorTask::Revive;
	Self->ClaimedTarget = bClaims ? Option.Target : TWeakObjectPtr<AActor>();

	Self->CurrentTask = Option.Task;
	Self->TaskDetail = SurvivalNames::TaskName(Option.Task);

	if (Option.Task == ESurvivorTask::Idle)
	{
		IdleSpot = State()->Safehouse->GetRandomCampSpot();
	}

	// A few callouts so the squad's coordination is visible to the spectator.
	switch (Option.Task)
	{
	case ESurvivorTask::Gather:
		Self->TaskDetail = FString::Printf(TEXT("Gathering %s"), *SurvivalNames::ResourceName(Option.Resource));
		if (Previous != ESurvivorTask::Gather)
		{
			SayOnce(FString::Printf(TEXT("I'll get %s."), *SurvivalNames::ResourceName(Option.Resource)), 25.f);
		}
		break;
	case ESurvivorTask::Revive:
		if (const ASurvivorCharacter* Ally = Cast<ASurvivorCharacter>(Option.Target.Get()))
		{
			Self->TaskDetail = FString::Printf(TEXT("Reviving %s"), *Ally->SurvivorName);
			SayOnce(FString::Printf(TEXT("Hang on, %s! I'm coming!"), *Ally->SurvivorName), 4.f);
		}
		break;
	case ESurvivorTask::Fight:
		if (const AZombieCharacter* Zombie = Cast<AZombieCharacter>(Option.Target.Get()))
		{
			for (const ASurvivorCharacter* Ally : State()->Survivors)
			{
				if (Ally && Ally != Self && Ally->CanAct() && FVector::Dist2D(Ally->GetActorLocation(), Zombie->GetActorLocation()) < 350.f)
				{
					Self->TaskDetail = FString::Printf(TEXT("Covering %s"), *Ally->SurvivorName);
					SayOnce(FString::Printf(TEXT("%s, I've got your back!"), *Ally->SurvivorName), 15.f);
					break;
				}
			}
		}
		break;
	case ESurvivorTask::Flee:
		SayOnce(TEXT("I'm hurt bad, falling back!"), 15.f);
		break;
	case ESurvivorTask::Repair:
		if (State()->GetNightUrgency() > 0.f)
		{
			SayOnce(TEXT("Shoring up the walls before dark."), 30.f);
		}
		break;
	default:
		break;
	}
}

void ASurvivorAIController::SayOnce(const FString& Line, float Cooldown)
{
	const float Now = GetWorld()->GetTimeSeconds();
	if (Now - LastLineTime >= Cooldown && Me()->GetSpeech().IsEmpty())
	{
		LastLineTime = Now;
		Me()->Say(Line);
	}
}

// --- Acting ------------------------------------------------------------------------------------

void ASurvivorAIController::Execute(float DeltaSeconds)
{
	ASurvivorCharacter* Self = Me();
	ASurvivalGameState* GS = State();
	ASafehouse* Camp = GS->Safehouse;
	const FVector Pos = Self->GetActorLocation();
	const float WorkSpeed = 0.75f + 0.5f * Self->Diligence;

	auto Finish = [this]()
	{
		// Pick something new at the start of next tick (Decide runs before Execute).
		DecideTimer = 0.f;
		bNeedsNewTask = true;
	};

	switch (Current.Task)
	{
	case ESurvivorTask::Gather:
	{
		AResourceNode* Node = Cast<AResourceNode>(Current.Target.Get());
		if (!Node || !Node->HasResources() || Self->CarriedAmount >= ASurvivorCharacter::MaxCarry)
		{
			Finish();
			break;
		}
		if (SurvivalSteering::MoveTowards(Self, Node->GetActorLocation(), WorkRange))
		{
			WorkTimer += DeltaSeconds * WorkSpeed;
			if (WorkTimer >= 1.3f)
			{
				WorkTimer = 0.f;
				if (Node->TakeOne())
				{
					Self->AddCarried(Node->GetResourceType());
				}
			}
		}
		break;
	}

	case ESurvivorTask::Deposit:
		if (SurvivalSteering::MoveTowards(Self, Camp->GetActorLocation(), Camp->Radius * 0.5f))
		{
			if (Self->CarriedAmount > 0)
			{
				GS->AddResource(Self->CarriedType, Self->CarriedAmount);
				GS->AddLog(FString::Printf(TEXT("%s brought back %d %s."), *Self->SurvivorName, Self->CarriedAmount,
				                           *SurvivalNames::ResourceName(Self->CarriedType)), FLinearColor(0.75f, 0.85f, 1.f));
				Self->ClearCarried();
			}
			Finish();
		}
		break;

	case ESurvivorTask::Eat:
	{
		const bool bOwnFood = Self->CarriedType == EResourceType::Food && Self->CarriedAmount > 0;
		if (!bOwnFood && GS->Food <= 0)
		{
			Finish();
			break;
		}
		if (bOwnFood || SurvivalSteering::MoveTowards(Self, Camp->GetActorLocation(), Camp->Radius * 0.5f))
		{
			WorkTimer += DeltaSeconds;
			if (WorkTimer >= 2.f)
			{
				if (bOwnFood)
				{
					--Self->CarriedAmount;
					if (Self->CarriedAmount == 0)
					{
						Self->ClearCarried();
					}
				}
				else
				{
					GS->AddResource(EResourceType::Food, -1);
				}
				Self->Fullness = FMath::Min(100.f, Self->Fullness + 45.f);
				Finish();
			}
		}
		break;
	}

	case ESurvivorTask::Rest:
		if (SurvivalSteering::MoveTowards(Self, Camp->GetActorLocation(), 260.f))
		{
			Self->Stamina = FMath::Min(100.f, Self->Stamina + 12.f * DeltaSeconds);
			if (Self->Fullness > 20.f)
			{
				Self->Health = FMath::Min(Self->MaxHealth, Self->Health + 2.5f * DeltaSeconds);
			}
			if (Self->Stamina >= 95.f && Self->Health >= Self->MaxHealth * 0.9f)
			{
				Finish();
			}
		}
		break;

	case ESurvivorTask::Repair:
	{
		if (GS->Wood <= 0 || GS->BarricadeHealth >= GS->MaxBarricadeHealth)
		{
			Finish();
			break;
		}
		// Work on the side of the ring closest to any approaching zombie, otherwise the nearest side.
		const AZombieCharacter* Threat = NearestZombie(Camp->GetActorLocation(), 3000.f);
		const FVector Spot = Camp->GetRingPoint(Threat ? Threat->GetActorLocation() : Pos, -80.f);
		if (SurvivalSteering::MoveTowards(Self, Spot, 120.f))
		{
			WorkTimer += DeltaSeconds * WorkSpeed;
			if (WorkTimer >= 1.5f)
			{
				WorkTimer = 0.f;
				GS->AddResource(EResourceType::Wood, -1);
				GS->BarricadeHealth = FMath::Min(GS->MaxBarricadeHealth, GS->BarricadeHealth + 15.f);
			}
		}
		break;
	}

	case ESurvivorTask::Craft:
		if (GS->Scrap < ASurvivalGameState::ScrapPerUpgrade || GS->WeaponLevel >= ASurvivalGameState::MaxWeaponLevel)
		{
			Finish();
			break;
		}
		if (SurvivalSteering::MoveTowards(Self, Camp->GetActorLocation(), 250.f))
		{
			WorkTimer += DeltaSeconds * WorkSpeed;
			if (WorkTimer >= 5.f)
			{
				GS->AddResource(EResourceType::Scrap, -ASurvivalGameState::ScrapPerUpgrade);
				++GS->WeaponLevel;
				GS->AddLog(FString::Printf(TEXT("%s upgraded the squad's weapons to level %d."), *Self->SurvivorName, GS->WeaponLevel),
				           FLinearColor(0.6f, 0.8f, 1.f));
				Self->Say(TEXT("New weapons, everyone. Make them count."));
				Finish();
			}
		}
		break;

	case ESurvivorTask::Fight:
	{
		AZombieCharacter* Zombie = Cast<AZombieCharacter>(Current.Target.Get());
		if (!Zombie || Zombie->IsDead())
		{
			Finish();
			break;
		}
		// Don't chase zombies across the map.
		if (FVector::Dist2D(Pos, Zombie->GetActorLocation()) > 2500.f)
		{
			Finish();
			break;
		}
		if (SurvivalSteering::MoveTowards(Self, Zombie->GetActorLocation(), MeleeRange * 0.8f) ||
			FVector::Dist2D(Pos, Zombie->GetActorLocation()) < MeleeRange)
		{
			Self->TryAttack(Zombie);
		}
		break;
	}

	case ESurvivorTask::Flee:
	{
		const AZombieCharacter* Threat = Cast<AZombieCharacter>(Current.Target.Get());
		FVector Goal;
		if (GS->BarricadeHealth > 0.f)
		{
			Goal = Camp->GetActorLocation(); // Run for the walls.
		}
		else
		{
			const FVector Away = Threat ? (Pos - Threat->GetActorLocation()).GetSafeNormal2D() : FVector::ForwardVector;
			Goal = Pos + Away * 800.f;
		}
		if (SurvivalSteering::MoveTowards(Self, Goal, 200.f) || !Threat || Threat->IsDead() ||
			FVector::Dist2D(Pos, Threat->GetActorLocation()) > 1200.f)
		{
			Finish();
		}
		break;
	}

	case ESurvivorTask::Revive:
	{
		ASurvivorCharacter* Ally = Cast<ASurvivorCharacter>(Current.Target.Get());
		if (!Ally || !Ally->IsDowned())
		{
			Finish();
			break;
		}
		if (SurvivalSteering::MoveTowards(Self, Ally->GetActorLocation(), 120.f))
		{
			Self->SetSprinting(false);
			WorkTimer += DeltaSeconds;
			Self->TaskDetail = FString::Printf(TEXT("Reviving %s (%.0f%%)"), *Ally->SurvivorName, FMath::Min(100.f, WorkTimer / 3.5f * 100.f));
			if (WorkTimer >= 3.5f)
			{
				Ally->Revive(Self);
				Finish();
			}
		}
		break;
	}

	case ESurvivorTask::Defend:
	{
		// Stand just inside the ring on the threatened side and strike anything that reaches it.
		const AZombieCharacter* Threat = NearestZombie(Camp->GetActorLocation(), Camp->Radius + 1500.f);
		if (!Threat)
		{
			SurvivalSteering::MoveTowards(Self, Camp->GetRingPoint(Pos, -120.f), 100.f);
			break;
		}
		AZombieCharacter* InReach = NearestZombie(Pos, MeleeRange + 60.f);
		if (InReach)
		{
			Self->TryAttack(InReach);
		}
		else
		{
			SurvivalSteering::MoveTowards(Self, Camp->GetRingPoint(Threat->GetActorLocation(), -70.f), 60.f);
		}
		break;
	}

	case ESurvivorTask::Idle:
	default:
		if (SurvivalSteering::MoveTowards(Self, IdleSpot, 80.f))
		{
			WorkTimer += DeltaSeconds;
			if (WorkTimer > 6.f)
			{
				WorkTimer = 0.f;
				IdleSpot = Camp->GetRandomCampSpot();
			}
		}
		break;
	}
}
