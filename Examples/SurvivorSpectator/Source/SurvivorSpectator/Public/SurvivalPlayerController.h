#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "SurvivalPlayerController.generated.h"

class ASurvivalSpectatorPawn;
class ASurvivorCharacter;

/** Spectator controls: pick who to watch, switch camera modes, and change game speed. */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivalPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ASurvivalPlayerController();

	virtual void BeginPlay() override;
	virtual void PlayerTick(float DeltaTime) override;

	ASurvivorCharacter* GetWatched() const { return Watched.Get(); }
	bool IsFollowingLeader() const { return bFollowLeader; }
	bool IsHudVisible() const { return bShowHud; }
	bool ShowHelp() const { return bShowHelp; }
	float GetTimeScale() const;

private:
	ASurvivalSpectatorPawn* SpectatorPawn() const;
	void HandleKeys();
	void Watch(ASurvivorCharacter* Survivor, bool bLeaderMode);
	void CycleWatched(int32 Direction);
	void SetSpeedStep(int32 Step);

	TWeakObjectPtr<ASurvivorCharacter> Watched;
	bool bFollowLeader = true;
	bool bShowHud = true;
	bool bShowHelp = true;
	int32 SpeedStep = 2;
};
