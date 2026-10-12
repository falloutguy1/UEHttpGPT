#include "SurvivalHUD.h"

#include "Camera/PlayerCameraManager.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "SurvivalGameState.h"
#include "SurvivalPlayerController.h"
#include "SurvivorCharacter.h"

namespace
{
	FString Clock(float Seconds)
	{
		const int32 Total = FMath::Max(0, FMath::RoundToInt(Seconds));
		return FString::Printf(TEXT("%d:%02d"), Total / 60, Total % 60);
	}

	const FLinearColor Gold(1.f, 0.82f, 0.25f);
	const FLinearColor Dim(0.65f, 0.65f, 0.7f);
}

void ASurvivalHUD::DrawHUD()
{
	Super::DrawHUD();

	const ASurvivalGameState* GS = GetWorld()->GetGameState<ASurvivalGameState>();
	const ASurvivalPlayerController* PC = Cast<ASurvivalPlayerController>(GetOwningPlayerController());
	if (!GS || !PC || !Canvas)
	{
		return;
	}

	UI = FMath::Max(0.6f, Canvas->ClipY / 1080.f);

	DrawWorldTags(GS, PC);
	if (PC->IsHudVisible())
	{
		DrawStatus(GS, PC);
		DrawRoster(GS, PC);
		DrawLeaderPanel(GS);
		DrawLog(GS);
		if (PC->ShowHelp())
		{
			DrawHelp();
		}
	}
	if (GS->bGameOver)
	{
		DrawGameOver(GS);
	}
}

void ASurvivalHUD::Text(const FString& String, float X, float Y, const FLinearColor& Color, UFont* Font, float Scale, bool bCentre)
{
	float W = 0.f, H = 0.f;
	if (bCentre)
	{
		GetTextSize(String, W, H, Font, Scale * UI);
	}
	// Drop shadow keeps text readable against bright daylight.
	DrawText(String, FLinearColor(0, 0, 0, 0.8f), X - W * 0.5f + 1.5f, Y + 1.5f, Font, Scale * UI);
	DrawText(String, Color, X - W * 0.5f, Y, Font, Scale * UI);
}

void ASurvivalHUD::Bar(float X, float Y, float W, float H, float Ratio, const FLinearColor& Color)
{
	DrawRect(FLinearColor(0, 0, 0, 0.6f), X, Y, W, H);
	DrawRect(Color, X + 1, Y + 1, (W - 2) * FMath::Clamp(Ratio, 0.f, 1.f), H - 2);
}

void ASurvivalHUD::Panel(float X, float Y, float W, float H)
{
	DrawRect(FLinearColor(0.02f, 0.02f, 0.03f, 0.6f), X, Y, W, H);
}

void ASurvivalHUD::DrawWorldTags(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC)
{
	UFont* Small = GEngine->GetSmallFont();
	const FVector CamLoc = PC->PlayerCameraManager ? PC->PlayerCameraManager->GetCameraLocation() : FVector::ZeroVector;
	const FVector CamDir = PC->PlayerCameraManager ? PC->PlayerCameraManager->GetCameraRotation().Vector() : FVector::ForwardVector;

	for (const ASurvivorCharacter* Survivor : GS->Survivors)
	{
		if (!Survivor)
		{
			continue;
		}
		const FVector Head = Survivor->GetActorLocation() + FVector(0, 0, 120);
		if (FVector::DotProduct(Head - CamLoc, CamDir) <= 0.f || FVector::Dist(Head, CamLoc) > 6000.f)
		{
			continue; // Behind the camera or too far to read.
		}
		const FVector Screen = Project(Head);
		const float X = Screen.X;
		float Y = Screen.Y;

		const bool bWatched = Survivor == PC->GetWatched();
		FString Name = Survivor->bIsLeader ? FString::Printf(TEXT("* %s *"), *Survivor->SurvivorName) : Survivor->SurvivorName;
		if (Survivor->IsDead())
		{
			Text(Name + TEXT(" (dead)"), X, Y, Dim, Small, 1.f, true);
			continue;
		}

		if (!Survivor->GetSpeech().IsEmpty())
		{
			const FString Quote = TEXT("\"") + Survivor->GetSpeech() + TEXT("\"");
			float W = 0.f, H = 0.f;
			GetTextSize(Quote, W, H, Small, UI);
			DrawRect(FLinearColor(1.f, 1.f, 1.f, 0.85f), X - W * 0.5f - 6.f, Y - 46.f * UI, W + 12.f, H + 6.f);
			DrawText(Quote, FLinearColor(0.05f, 0.05f, 0.05f), X - W * 0.5f, Y - 43.f * UI, Small, UI);
		}

		Text(Name, X, Y - 18.f * UI, bWatched ? Gold : FMath::Lerp(Survivor->Color, FLinearColor::White, 0.4f), Small, 1.f, true);
		const float BarW = 70.f * UI;
		if (Survivor->IsDowned())
		{
			Bar(X - BarW * 0.5f, Y, BarW, 6.f * UI, Survivor->GetBleedOut() / 35.f, FLinearColor(0.9f, 0.1f, 0.1f));
			Text(TEXT("DOWNED"), X, Y + 8.f * UI, FLinearColor(1.f, 0.3f, 0.3f), Small, 0.9f, true);
		}
		else
		{
			Bar(X - BarW * 0.5f, Y, BarW, 6.f * UI, Survivor->Health / Survivor->MaxHealth, FLinearColor(0.2f, 0.85f, 0.3f));
			Text(Survivor->TaskDetail, X, Y + 8.f * UI, Dim, Small, 0.9f, true);
		}
	}
}

void ASurvivalHUD::DrawStatus(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC)
{
	UFont* Medium = GEngine->GetMediumFont();
	UFont* Small = GEngine->GetSmallFont();
	const float X = 20.f * UI;
	float Y = 20.f * UI;

	Panel(X - 10.f * UI, Y - 8.f * UI, 380.f * UI, 170.f * UI);

	const FString Phase = GS->IsNight()
		? FString::Printf(TEXT("NIGHT %d  -  dawn in %s"), GS->Day, *Clock(GS->SecondsUntilDawn()))
		: FString::Printf(TEXT("DAY %d  -  night in %s"), GS->Day, *Clock(GS->SecondsUntilNight()));
	Text(Phase, X, Y, GS->IsNight() ? FLinearColor(0.6f, 0.65f, 1.f) : Gold, Medium);
	Y += 28.f * UI;

	Text(FString::Printf(TEXT("Survive until dawn of day %d"), GS->DaysToSurvive + 1), X, Y, Dim, Small);
	Y += 22.f * UI;

	Text(FString::Printf(TEXT("Food %d    Wood %d    Scrap %d    Weapons Lv %d"), GS->Food, GS->Wood, GS->Scrap, GS->WeaponLevel), X, Y,
	     FLinearColor::White, Small);
	Y += 22.f * UI;

	Text(TEXT("Barricade"), X, Y, FLinearColor::White, Small);
	Bar(X + 90.f * UI, Y + 3.f * UI, 250.f * UI, 12.f * UI, GS->BarricadeHealth / GS->MaxBarricadeHealth, FLinearColor(0.75f, 0.5f, 0.2f));
	Y += 22.f * UI;

	Text(FString::Printf(TEXT("Zombies %d    Killed %d"), GS->Zombies.Num(), GS->ZombiesKilled), X, Y, FLinearColor(0.7f, 1.f, 0.6f), Small);
	Y += 22.f * UI;

	const float Speed = PC->GetTimeScale();
	Text(Speed <= 0.f ? TEXT("PAUSED") : FString::Printf(TEXT("Speed x%g"), Speed), X, Y, Speed <= 0.f ? FLinearColor(1.f, 0.4f, 0.4f) : Dim, Small);
}

void ASurvivalHUD::DrawRoster(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC)
{
	UFont* Small = GEngine->GetSmallFont();
	const float X = 20.f * UI;
	float Y = 210.f * UI;
	const float RowH = 44.f * UI;

	Panel(X - 10.f * UI, Y - 8.f * UI, 380.f * UI, GS->Survivors.Num() * RowH + 34.f * UI);
	Text(TEXT("SQUAD"), X, Y, Gold, Small);
	Y += 24.f * UI;

	for (int32 i = 0; i < GS->Survivors.Num(); ++i)
	{
		const ASurvivorCharacter* S = GS->Survivors[i];
		if (!S)
		{
			continue;
		}
		const bool bWatched = S == PC->GetWatched();
		if (bWatched)
		{
			DrawRect(FLinearColor(1.f, 0.8f, 0.2f, 0.15f), X - 6.f * UI, Y - 3.f * UI, 368.f * UI, RowH - 4.f * UI);
		}

		DrawRect(S->Color, X, Y + 2.f * UI, 10.f * UI, 10.f * UI);
		const FString Name = FString::Printf(TEXT("%d  %s%s"), i + 1, *S->SurvivorName, S->bIsLeader ? TEXT("  (leader)") : TEXT(""));
		Text(Name, X + 16.f * UI, Y - 2.f * UI, S->IsDead() ? Dim : FLinearColor::White, Small);

		if (S->IsDead())
		{
			Text(TEXT("dead"), X + 200.f * UI, Y - 2.f * UI, FLinearColor(0.8f, 0.3f, 0.3f), Small);
		}
		else
		{
			Bar(X + 200.f * UI, Y + 1.f * UI, 70.f * UI, 8.f * UI, S->Health / S->MaxHealth, FLinearColor(0.2f, 0.85f, 0.3f));
			Bar(X + 275.f * UI, Y + 1.f * UI, 40.f * UI, 8.f * UI, S->Fullness / 100.f, FLinearColor(0.9f, 0.6f, 0.2f));
			Bar(X + 320.f * UI, Y + 1.f * UI, 35.f * UI, 8.f * UI, S->Stamina / 100.f, FLinearColor(0.3f, 0.6f, 1.f));
			FString Detail = S->IsDowned() ? FString::Printf(TEXT("DOWNED - %.0fs to bleed out"), S->GetBleedOut()) : S->TaskDetail;
			if (S->CarriedAmount > 0)
			{
				Detail += FString::Printf(TEXT("  [%d %s]"), S->CarriedAmount, *SurvivalNames::ResourceName(S->CarriedType));
			}
			Text(Detail, X + 16.f * UI, Y + 16.f * UI, S->IsDowned() ? FLinearColor(1.f, 0.35f, 0.35f) : Dim, Small, 0.9f);
		}
		Y += RowH;
	}
}

void ASurvivalHUD::DrawLeaderPanel(const ASurvivalGameState* GS)
{
	const ASurvivorCharacter* Leader = GS->GetLeader();
	if (!Leader)
	{
		return;
	}
	UFont* Small = GEngine->GetSmallFont();
	const float W = 760.f * UI;
	const float X = (Canvas->ClipX - W) * 0.5f;
	const float Y = Canvas->ClipY - 120.f * UI;

	Panel(X, Y, W, 92.f * UI);
	Text(FString::Printf(TEXT("%s's plan: %s"), *Leader->SurvivorName, *SurvivalNames::DirectiveName(GS->Directive).Replace(TEXT("_"), TEXT(" ")).ToUpper()),
	     X + 12.f * UI, Y + 8.f * UI, Gold, Small);
	Text(FString::Printf(TEXT("brain: %s"), *GS->BrainMode), X + W - 260.f * UI, Y + 8.f * UI, Dim, Small, 0.9f);

	// Wrap the thought onto up to three lines.
	TArray<FString> Words;
	GS->LeaderThought.ParseIntoArray(Words, TEXT(" "));
	FString Line = TEXT("thinking: ");
	float LineY = Y + 32.f * UI;
	for (const FString& Word : Words)
	{
		float LW = 0.f, LH = 0.f;
		GetTextSize(Line + Word, LW, LH, Small, UI);
		if (LW > W - 30.f * UI)
		{
			Text(Line, X + 12.f * UI, LineY, FLinearColor(0.85f, 0.85f, 1.f), Small);
			LineY += 18.f * UI;
			Line.Reset();
		}
		Line += Word + TEXT(" ");
	}
	Text(Line, X + 12.f * UI, LineY, FLinearColor(0.85f, 0.85f, 1.f), Small);
}

void ASurvivalHUD::DrawLog(const ASurvivalGameState* GS)
{
	UFont* Small = GEngine->GetSmallFont();
	const float W = 470.f * UI;
	const float X = Canvas->ClipX - W - 20.f * UI;
	float Y = 20.f * UI;
	constexpr int32 Lines = 16;
	const float Now = GetWorld()->GetRealTimeSeconds();

	Panel(X - 10.f * UI, Y - 8.f * UI, W + 20.f * UI, (Lines * 19.f + 34.f) * UI);
	Text(TEXT("EVENTS"), X, Y, Gold, Small);
	Y += 24.f * UI;

	const int32 First = FMath::Max(0, GS->Log.Num() - Lines);
	for (int32 i = First; i < GS->Log.Num(); ++i)
	{
		const FSurvivalLogEntry& Entry = GS->Log[i];
		FLinearColor Color = Entry.Color;
		Color.A = FMath::Clamp(1.f - (Now - Entry.RealTime - 30.f) / 30.f, 0.45f, 1.f); // Older entries fade.

		FString Display = Entry.Text;
		float TW = 0.f, TH = 0.f;
		GetTextSize(Display, TW, TH, Small, UI);
		while (TW > W && Display.Len() > 4)
		{
			Display = Display.LeftChop(4) + TEXT("...");
			GetTextSize(Display, TW, TH, Small, UI);
		}
		Text(Display, X, Y, Color, Small);
		Y += 19.f * UI;
	}
}

void ASurvivalHUD::DrawHelp()
{
	UFont* Small = GEngine->GetSmallFont();
	const FString Help = TEXT("Tab/arrows or 1-8: watch survivor   L: follow leader   C/T/F: follow/tactical/free cam   "
		"wheel: zoom   [ ]: speed   Space: pause   H: hide HUD   F1: hide help");
	Text(Help, Canvas->ClipX * 0.5f, Canvas->ClipY - 22.f * UI, Dim, Small, 0.9f, true);
}

void ASurvivalHUD::DrawGameOver(const ASurvivalGameState* GS)
{
	UFont* Large = GEngine->GetLargeFont();
	UFont* Small = GEngine->GetSmallFont();
	const float CX = Canvas->ClipX * 0.5f;
	const float CY = Canvas->ClipY * 0.35f;

	DrawRect(FLinearColor(0, 0, 0, 0.55f), 0, CY - 30.f * UI, Canvas->ClipX, 120.f * UI);
	Text(GS->bVictory ? TEXT("THEY SURVIVED") : TEXT("EVERYONE IS GONE"), CX, CY, GS->bVictory ? Gold : FLinearColor(1.f, 0.3f, 0.3f), Large, 2.f, true);

	int32 Alive = 0;
	for (const ASurvivorCharacter* S : GS->Survivors)
	{
		Alive += (S && !S->IsDead()) ? 1 : 0;
	}
	Text(FString::Printf(TEXT("Day %d  -  %d of %d survivors alive  -  %d zombies killed  -  press R to restart"), GS->Day, Alive,
	                     GS->Survivors.Num(), GS->ZombiesKilled), CX, CY + 50.f * UI, FLinearColor::White, Small, 1.f, true);
}
