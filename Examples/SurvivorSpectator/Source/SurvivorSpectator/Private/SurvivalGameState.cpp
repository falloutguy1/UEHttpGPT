#include "SurvivalGameState.h"

#include "Safehouse.h"
#include "SurvivorCharacter.h"

ASurvivalGameState::ASurvivalGameState()
{
	PrimaryActorTick.bCanEverTick = true;
}

void ASurvivalGameState::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (bGameOver)
	{
		return;
	}

	const bool bWasNight = IsNight();
	DayFraction += DeltaSeconds / DayLength;

	if (DayFraction >= 1.f)
	{
		DayFraction -= 1.f;
		++Day;
		if (Day > DaysToSurvive)
		{
			bGameOver = true;
			bVictory = true;
			AddLog(FString::Printf(TEXT("Dawn breaks. The squad survived %d nights!"), DaysToSurvive), FLinearColor(1.f, 0.85f, 0.2f));
			return;
		}
		AddLog(FString::Printf(TEXT("Dawn of day %d."), Day), FLinearColor(1.f, 0.9f, 0.5f));
		OnDawn.Broadcast();
	}
	else if (!bWasNight && IsNight())
	{
		AddLog(FString::Printf(TEXT("Night %d falls. They're coming."), Day), FLinearColor(0.6f, 0.6f, 1.f));
		OnNightfall.Broadcast();
	}
}

float ASurvivalGameState::GetNightUrgency() const
{
	if (IsNight())
	{
		return 1.f;
	}
	// Starts rising 50 game seconds before dusk.
	return FMath::Clamp(1.f - SecondsUntilNight() / 50.f, 0.f, 1.f);
}

void ASurvivalGameState::AddResource(EResourceType Type, int32 Amount)
{
	switch (Type)
	{
	case EResourceType::Food: Food = FMath::Max(0, Food + Amount); break;
	case EResourceType::Wood: Wood = FMath::Max(0, Wood + Amount); break;
	case EResourceType::Scrap: Scrap = FMath::Max(0, Scrap + Amount); break;
	default: break;
	}
}

int32 ASurvivalGameState::GetResource(EResourceType Type) const
{
	switch (Type)
	{
	case EResourceType::Food: return Food;
	case EResourceType::Wood: return Wood;
	case EResourceType::Scrap: return Scrap;
	default: return 0;
	}
}

void ASurvivalGameState::DamageBarricade(float Amount)
{
	if (BarricadeHealth <= 0.f)
	{
		return;
	}
	BarricadeHealth = FMath::Max(0.f, BarricadeHealth - Amount);
	if (BarricadeHealth <= 0.f)
	{
		AddLog(TEXT("The barricade has fallen! The camp is open."), FLinearColor(1.f, 0.3f, 0.2f));
	}
}

void ASurvivalGameState::SetDirective(ESquadDirective NewDirective)
{
	Directive = NewDirective;
}

ASurvivorCharacter* ASurvivalGameState::GetLeader() const
{
	for (ASurvivorCharacter* Survivor : Survivors)
	{
		if (Survivor && Survivor->bIsLeader && !Survivor->IsDead())
		{
			return Survivor;
		}
	}
	return nullptr;
}

void ASurvivalGameState::EnsureLeader()
{
	if (GetLeader() || bGameOver)
	{
		return;
	}

	ASurvivorCharacter* Best = nullptr;
	float BestScore = -1.f;
	for (ASurvivorCharacter* Survivor : Survivors)
	{
		if (Survivor && !Survivor->IsDead())
		{
			const float Score = Survivor->Bravery + Survivor->Cooperation + (Survivor->IsDowned() ? -1.f : 0.f);
			if (Score > BestScore)
			{
				BestScore = Score;
				Best = Survivor;
			}
		}
	}

	for (ASurvivorCharacter* Survivor : Survivors)
	{
		if (Survivor)
		{
			Survivor->bIsLeader = (Survivor == Best);
		}
	}

	if (Best)
	{
		AddLog(FString::Printf(TEXT("%s steps up to lead the squad."), *Best->SurvivorName), FLinearColor(1.f, 0.8f, 0.2f));
		Best->Say(TEXT("Listen up, I'm calling the shots now. We stick together."));
	}
	else
	{
		bGameOver = true;
		bVictory = false;
		AddLog(FString::Printf(TEXT("The last survivor has fallen on day %d."), Day), FLinearColor(1.f, 0.2f, 0.2f));
	}
}

TArray<ASurvivorCharacter*> ASurvivalGameState::GetLivingSurvivors() const
{
	TArray<ASurvivorCharacter*> Result;
	for (ASurvivorCharacter* Survivor : Survivors)
	{
		if (Survivor && !Survivor->IsDead())
		{
			Result.Add(Survivor);
		}
	}
	return Result;
}

bool ASurvivalGameState::IsClaimedByOther(const AActor* Target, const ASurvivorCharacter* Asker) const
{
	for (const ASurvivorCharacter* Survivor : Survivors)
	{
		if (Survivor && Survivor != Asker && !Survivor->IsDead() && Survivor->ClaimedTarget.Get() == Target)
		{
			return true;
		}
	}
	return false;
}

void ASurvivalGameState::AddLog(const FString& Text, const FLinearColor& Color)
{
	FSurvivalLogEntry& Entry = Log.AddDefaulted_GetRef();
	Entry.Text = Text;
	Entry.Color = Color;
	Entry.RealTime = GetWorld() ? GetWorld()->GetRealTimeSeconds() : 0.f;

	if (Log.Num() > 60)
	{
		Log.RemoveAt(0, Log.Num() - 60);
	}
	UE_LOG(LogTemp, Log, TEXT("[Survival] %s"), *Text);
}
