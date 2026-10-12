#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "SurvivalHUD.generated.h"

class ASurvivalGameState;
class ASurvivalPlayerController;
class UFont;

/** Canvas overlay: clock and camp status, squad roster, the leader's thoughts, the event feed and name tags. */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivalHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;

private:
	void DrawWorldTags(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC);
	void DrawStatus(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC);
	void DrawRoster(const ASurvivalGameState* GS, const ASurvivalPlayerController* PC);
	void DrawLeaderPanel(const ASurvivalGameState* GS);
	void DrawLog(const ASurvivalGameState* GS);
	void DrawHelp();
	void DrawGameOver(const ASurvivalGameState* GS);

	void Text(const FString& String, float X, float Y, const FLinearColor& Color, UFont* Font, float Scale = 1.f, bool bCentre = false);
	void Bar(float X, float Y, float W, float H, float Ratio, const FLinearColor& Color);
	void Panel(float X, float Y, float W, float H);

	float UI = 1.f;
};
