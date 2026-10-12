#include "LeaderBrainComponent.h"

#include "Dom/JsonObject.h"
#include "Management/HttpGPTSettings.h"
#include "Safehouse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "SurvivalGameState.h"
#include "SurvivorCharacter.h"
#include "Tasks/HttpGPTChatRequest.h"
#include "ZombieCharacter.h"

namespace
{
	/** After this many failed GPT calls in a row the leader stops trying and sticks to the rule-based brain. */
	constexpr int32 MaxGPTFailures = 3;

	const TCHAR* SystemPrompt = TEXT(
		"You are the leader of a small group of survivors in a zombie apocalypse, shown in a game that people are spectating. "
		"Each turn you get a report on your squad and camp. Choose the squad's directive and speak to your team.\n"
		"Directives:\n"
		"- balanced: everyone works on whatever is most needed\n"
		"- stockpile_food: prioritise gathering food\n"
		"- gather_wood: prioritise wood (fuel for barricade repairs)\n"
		"- scavenge_scrap: prioritise scrap (5 scrap upgrades everyone's weapons)\n"
		"- fortify: repair the barricade, haul wood home\n"
		"- protect_each_other: stop working, defend and revive teammates\n"
		"- regroup: everyone back inside the camp now\n"
		"Zombies hunt everyone at night and must break the barricade to reach people inside it. Downed survivors die unless revived.\n"
		"Reply with ONLY a JSON object, no markdown: "
		"{\"directive\": \"<one directive>\", \"say\": \"<one short line you shout to the squad, max 15 words>\", "
		"\"thought\": \"<your private reasoning in first person, max 25 words>\"}");

	FString StripCodeFence(FString Text)
	{
		Text.TrimStartAndEndInline();
		int32 Open = INDEX_NONE;
		int32 Close = INDEX_NONE;
		if (Text.FindChar(TEXT('{'), Open) && Text.FindLastChar(TEXT('}'), Close) && Close > Open)
		{
			return Text.Mid(Open, Close - Open + 1);
		}
		return Text;
	}
}

ULeaderBrainComponent::ULeaderBrainComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickInterval = 0.5f;
}

ASurvivorCharacter* ULeaderBrainComponent::Owner() const
{
	return Cast<ASurvivorCharacter>(GetOwner());
}

ASurvivalGameState* ULeaderBrainComponent::State() const
{
	return GetWorld() ? GetWorld()->GetGameState<ASurvivalGameState>() : nullptr;
}

void ULeaderBrainComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	const ASurvivorCharacter* Self = Owner();
	const ASurvivalGameState* GS = State();
	if (!Self || !GS || !Self->bIsLeader || Self->IsDead() || GS->bGameOver)
	{
		return;
	}

	SinceThink += DeltaTime;
	const bool bRoutine = SinceThink >= ThinkInterval;
	const bool bUrgent = PendingReasons.Num() > 0 && SinceThink >= MinThinkGap;
	if ((bRoutine || bUrgent) && !bRequestInFlight)
	{
		Think();
	}
}

void ULeaderBrainComponent::RequestThink(const FString& Reason)
{
	PendingReasons.AddUnique(Reason);
}

void ULeaderBrainComponent::Think()
{
	SinceThink = 0.f;
	bSpeakOnApply = PendingReasons.Num() > 0;
	if (!ThinkWithGPT())
	{
		ThinkWithRules();
	}
	PendingReasons.Reset();
}

FString ULeaderBrainComponent::DescribeSituation() const
{
	const ASurvivalGameState* GS = State();
	const ASurvivorCharacter* Self = Owner();

	FString Text = FString::Printf(TEXT("You are %s. Day %d of %d. "), *Self->SurvivorName, GS->Day, GS->DaysToSurvive);
	Text += GS->IsNight()
		? FString::Printf(TEXT("It is NIGHT, dawn in %.0fs.\n"), GS->SecondsUntilDawn())
		: FString::Printf(TEXT("It is day, night falls in %.0fs.\n"), GS->SecondsUntilNight());

	Text += FString::Printf(TEXT("Camp stockpile: food %d, wood %d, scrap %d. Weapon level %d/%d. Barricade %.0f/%.0f.\n"), GS->Food, GS->Wood,
	                        GS->Scrap, GS->WeaponLevel, ASurvivalGameState::MaxWeaponLevel, GS->BarricadeHealth, GS->MaxBarricadeHealth);

	int32 NearCamp = 0;
	for (const AZombieCharacter* Zombie : GS->Zombies)
	{
		if (Zombie && !Zombie->IsDead() && GS->Safehouse && FVector::Dist2D(Zombie->GetActorLocation(), GS->Safehouse->GetActorLocation()) < 2000.f)
		{
			++NearCamp;
		}
	}
	Text += FString::Printf(TEXT("Zombies alive: %d (%d near camp). Killed so far: %d.\n"), GS->Zombies.Num(), NearCamp, GS->ZombiesKilled);

	Text += TEXT("Squad:\n");
	for (const ASurvivorCharacter* Survivor : GS->Survivors)
	{
		if (!Survivor)
		{
			continue;
		}
		if (Survivor->IsDead())
		{
			Text += FString::Printf(TEXT("- %s: dead\n"), *Survivor->SurvivorName);
			continue;
		}
		Text += FString::Printf(TEXT("- %s%s: %s, health %.0f, fullness %.0f, %s%s\n"), *Survivor->SurvivorName,
		                        Survivor == Self ? TEXT(" (you)") : TEXT(""),
		                        Survivor->IsDowned() ? *FString::Printf(TEXT("DOWNED (%.0fs left)"), Survivor->GetBleedOut()) : TEXT("ok"),
		                        Survivor->Health, Survivor->Fullness, *Survivor->TaskDetail.ToLower(),
		                        GS->Safehouse && GS->Safehouse->IsInside(Survivor->GetActorLocation()) ? TEXT(", in camp") : TEXT(", outside"));
	}

	Text += FString::Printf(TEXT("Current directive: %s.\n"), *SurvivalNames::DirectiveName(GS->Directive));
	if (PendingReasons.Num() > 0)
	{
		Text += TEXT("Just happened: ") + FString::Join(PendingReasons, TEXT("; ")) + TEXT(".\n");
	}

	// Recent events give the model a sense of story.
	const int32 First = FMath::Max(0, GS->Log.Num() - 6);
	Text += TEXT("Recent log:\n");
	for (int32 i = First; i < GS->Log.Num(); ++i)
	{
		Text += TEXT("  ") + GS->Log[i].Text + TEXT("\n");
	}
	return Text;
}

bool ULeaderBrainComponent::ThinkWithGPT()
{
	if (GPTFailures >= MaxGPTFailures || UHttpGPTSettings::GetCommonOptions().APIKey.IsNone())
	{
		if (State())
		{
			State()->BrainMode = GPTFailures >= MaxGPTFailures ? TEXT("rule-based (GPT unavailable)") : TEXT("rule-based (no API key)");
		}
		return false;
	}

	FHttpGPTChatOptions ChatOptions; // Starts from the project's HttpGPT settings.
	ChatOptions.bStream = false;
	ChatOptions.MaxTokens = 200;
	ChatOptions.Temperature = 0.9f;

	const TArray<FHttpGPTChatMessage> Messages = {
		FHttpGPTChatMessage(EHttpGPTChatRole::System, SystemPrompt),
		FHttpGPTChatMessage(EHttpGPTChatRole::User, DescribeSituation()),
	};

	ActiveRequest = UHttpGPTChatRequest::SendMessages_CustomOptions(this, Messages, TArray<FHttpGPTFunction>(), FHttpGPTCommonOptions(), ChatOptions);
	if (!ActiveRequest)
	{
		return false;
	}
	ActiveRequest->ProcessCompleted.AddDynamic(this, &ULeaderBrainComponent::OnGPTCompleted);
	ActiveRequest->ErrorReceived.AddDynamic(this, &ULeaderBrainComponent::OnGPTFailed);
	ActiveRequest->RequestFailed.AddDynamic(this, &ULeaderBrainComponent::OnGPTRequestFailed);

	bRequestInFlight = true;
	if (ASurvivalGameState* GS = State())
	{
		GS->BrainMode = TEXT("GPT (thinking...)");
	}
	ActiveRequest->Activate();
	return true;
}

void ULeaderBrainComponent::OnGPTCompleted(const FHttpGPTChatResponse& Response)
{
	if (!bRequestInFlight)
	{
		return;
	}
	bRequestInFlight = false;
	ActiveRequest = nullptr;

	ASurvivorCharacter* Self = Owner();
	if (!Self || !Self->bIsLeader || Self->IsDead())
	{
		return; // Leadership changed while we were thinking.
	}

	TSharedPtr<FJsonObject> Json;
	if (Response.bSuccess && Response.Choices.Num() > 0)
	{
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(StripCodeFence(Response.Choices[0].Message.Content));
		FJsonSerializer::Deserialize(Reader, Json);
	}

	FString Directive, Say, Thought;
	if (!Json.IsValid() || !Json->TryGetStringField(TEXT("directive"), Directive))
	{
		HandleFailure();
		return;
	}
	Json->TryGetStringField(TEXT("say"), Say);
	Json->TryGetStringField(TEXT("thought"), Thought);

	GPTFailures = 0;
	if (ASurvivalGameState* GS = State())
	{
		GS->BrainMode = TEXT("GPT");
	}
	Apply(SurvivalNames::DirectiveFromName(Directive), Say, Thought);
}

void ULeaderBrainComponent::OnGPTFailed(const FHttpGPTChatResponse& Response)
{
	if (bRequestInFlight)
	{
		UE_LOG(LogTemp, Warning, TEXT("Leader brain GPT error: %s"), *Response.Error.Message);
		bRequestInFlight = false;
		HandleFailure();
	}
}

void ULeaderBrainComponent::OnGPTRequestFailed()
{
	if (bRequestInFlight)
	{
		bRequestInFlight = false;
		HandleFailure();
	}
}

void ULeaderBrainComponent::HandleFailure()
{
	ActiveRequest = nullptr;
	++GPTFailures;

	if (ASurvivalGameState* GS = State())
	{
		GS->BrainMode = GPTFailures >= MaxGPTFailures ? TEXT("rule-based (GPT unavailable)") : TEXT("rule-based (GPT error)");
	}
	// Don't leave the squad without a plan.
	ThinkWithRules();
}

void ULeaderBrainComponent::ThinkWithRules()
{
	const ASurvivalGameState* GS = State();
	const ASurvivorCharacter* Self = Owner();
	if (!GS || !Self)
	{
		return;
	}

	const TArray<ASurvivorCharacter*> Living = GS->GetLivingSurvivors();
	const ASurvivorCharacter* Downed = nullptr;
	for (const ASurvivorCharacter* Survivor : Living)
	{
		if (Survivor->IsDowned())
		{
			Downed = Survivor;
			break;
		}
	}

	const float BarricadeRatio = GS->BarricadeHealth / GS->MaxBarricadeHealth;
	const int32 Mouths = FMath::Max(1, Living.Num());
	const float Urgency = GS->GetNightUrgency();

	if (Downed)
	{
		Apply(ESquadDirective::ProtectEachOther, FString::Printf(TEXT("%s is down! Nobody gets left behind!"), *Downed->SurvivorName),
		      FString::Printf(TEXT("If we lose %s we lose a pair of hands. Everything else can wait."), *Downed->SurvivorName));
	}
	else if (GS->IsNight() && BarricadeRatio <= 0.f)
	{
		Apply(ESquadDirective::ProtectEachOther, TEXT("The wall's gone! Back to back, everyone!"),
		      TEXT("No barricade. Our only chance is to fight as one until sunrise."));
	}
	else if (GS->IsNight())
	{
		Apply(ESquadDirective::Regroup, TEXT("Everyone inside the wall. We hold till dawn."),
		      FString::Printf(TEXT("%.0f seconds to sunrise. Stay together, keep the barricade standing."), GS->SecondsUntilDawn()));
	}
	else if (Urgency > 0.f && BarricadeRatio < 0.7f)
	{
		Apply(ESquadDirective::Fortify, TEXT("Dark's coming. Patch that wall, now!"),
		      TEXT("The barricade won't survive another night like this. Every plank counts."));
	}
	else if (Urgency > 0.5f)
	{
		Apply(ESquadDirective::Regroup, TEXT("Wrap it up, head back to camp!"), TEXT("Nobody should be caught outside when they come."));
	}
	else if (GS->Food < Mouths * 2)
	{
		Apply(ESquadDirective::StockpileFood, TEXT("We're running low on food. Find something to eat."),
		      FString::Printf(TEXT("%d mouths and %d rations. That math kills us before the zombies do."), Mouths, GS->Food));
	}
	else if (BarricadeRatio < 0.5f || GS->Wood < 4)
	{
		Apply(ESquadDirective::GatherWood, TEXT("We need wood for the walls. Get chopping."),
		      TEXT("A strong wall means we sleep tonight. Wood first."));
	}
	else if (GS->WeaponLevel < ASurvivalGameState::MaxWeaponLevel && GS->Day >= 2)
	{
		Apply(ESquadDirective::ScavengeScrap, TEXT("Strip those wrecks. We need better weapons."),
		      TEXT("They get tougher each night. Our weapons have to keep up."));
	}
	else
	{
		Apply(ESquadDirective::Balanced, TEXT("Good work. Keep it steady, watch each other's backs."),
		      TEXT("For once things are under control. Don't get comfortable."));
	}
}

void ULeaderBrainComponent::Apply(ESquadDirective Directive, const FString& Say, const FString& Thought)
{
	ASurvivalGameState* GS = State();
	ASurvivorCharacter* Self = Owner();
	if (!GS || !Self)
	{
		return;
	}

	const bool bChanged = GS->Directive != Directive;
	GS->SetDirective(Directive);
	GS->LeaderThought = Thought;

	// Only speak up when the plan changes or something just happened, so the leader isn't repeating themselves.
	if (bChanged || bSpeakOnApply)
	{
		Self->Say(Say, 5.f);
		if (bChanged)
		{
			GS->AddLog(FString::Printf(TEXT("New plan from %s: %s"), *Self->SurvivorName, *SurvivalNames::DirectiveName(Directive).Replace(TEXT("_"), TEXT(" "))),
			           FLinearColor(1.f, 0.8f, 0.2f));
		}
	}
}
