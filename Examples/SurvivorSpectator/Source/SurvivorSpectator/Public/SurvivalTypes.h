#pragma once

#include "CoreMinimal.h"
#include "SurvivalTypes.generated.h"

UENUM(BlueprintType)
enum class EResourceType : uint8
{
	None,
	Food,
	Wood,
	Scrap
};

/** What a survivor is currently trying to do. Picked every decision tick by utility scoring. */
UENUM(BlueprintType)
enum class ESurvivorTask : uint8
{
	Idle,
	Gather,
	Deposit,
	Eat,
	Rest,
	Repair,
	Craft,
	Fight,
	Flee,
	Revive,
	Defend
};

/** Squad-wide plan set by the leader. Every survivor's task scores are biased toward it. */
UENUM(BlueprintType)
enum class ESquadDirective : uint8
{
	Balanced,
	StockpileFood,
	GatherWood,
	ScavengeScrap,
	Fortify,
	ProtectEachOther,
	Regroup
};

USTRUCT(BlueprintType)
struct FSurvivalLogEntry
{
	GENERATED_BODY()

	UPROPERTY(BlueprintReadOnly)
	FString Text;

	UPROPERTY(BlueprintReadOnly)
	FLinearColor Color = FLinearColor::White;

	UPROPERTY(BlueprintReadOnly)
	float RealTime = 0.f;
};

namespace SurvivalNames
{
	inline FString TaskName(ESurvivorTask Task)
	{
		switch (Task)
		{
		case ESurvivorTask::Gather: return TEXT("Gathering");
		case ESurvivorTask::Deposit: return TEXT("Hauling to camp");
		case ESurvivorTask::Eat: return TEXT("Eating");
		case ESurvivorTask::Rest: return TEXT("Resting");
		case ESurvivorTask::Repair: return TEXT("Repairing barricade");
		case ESurvivorTask::Craft: return TEXT("Crafting weapons");
		case ESurvivorTask::Fight: return TEXT("Fighting");
		case ESurvivorTask::Flee: return TEXT("Fleeing");
		case ESurvivorTask::Revive: return TEXT("Reviving ally");
		case ESurvivorTask::Defend: return TEXT("Defending camp");
		default: return TEXT("Idle");
		}
	}

	inline FString ResourceName(EResourceType Type)
	{
		switch (Type)
		{
		case EResourceType::Food: return TEXT("food");
		case EResourceType::Wood: return TEXT("wood");
		case EResourceType::Scrap: return TEXT("scrap");
		default: return TEXT("nothing");
		}
	}

	inline FString DirectiveName(ESquadDirective Directive)
	{
		switch (Directive)
		{
		case ESquadDirective::StockpileFood: return TEXT("stockpile_food");
		case ESquadDirective::GatherWood: return TEXT("gather_wood");
		case ESquadDirective::ScavengeScrap: return TEXT("scavenge_scrap");
		case ESquadDirective::Fortify: return TEXT("fortify");
		case ESquadDirective::ProtectEachOther: return TEXT("protect_each_other");
		case ESquadDirective::Regroup: return TEXT("regroup");
		default: return TEXT("balanced");
		}
	}

	inline ESquadDirective DirectiveFromName(const FString& Name)
	{
		for (uint8 i = 0; i <= static_cast<uint8>(ESquadDirective::Regroup); ++i)
		{
			const ESquadDirective D = static_cast<ESquadDirective>(i);
			if (Name.Equals(DirectiveName(D), ESearchCase::IgnoreCase))
			{
				return D;
			}
		}
		return ESquadDirective::Balanced;
	}
}
