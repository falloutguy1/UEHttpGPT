#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "SurvivalGameMode.generated.h"

class ADirectionalLight;
class AExponentialHeightFog;
class ASkyLight;
class ASurvivalGameState;

/**
 * Builds the whole arena at runtime (lighting, ground, camp, resources, survivors) so the game runs on an
 * empty map, then drives the day/night cycle and the zombie waves.
 */
UCLASS()
class SURVIVORSPECTATOR_API ASurvivalGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ASurvivalGameMode();

	virtual void StartPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	/** How many survivors start in the squad (1-8). */
	UPROPERTY(EditAnywhere, Category = "Survival", meta = (ClampMin = 1, ClampMax = 8))
	int32 SquadSize = 6;

private:
	ASurvivalGameState* GS() const;

	void BuildLighting();
	void BuildArena();
	void SpawnSquad();

	void SpawnZombie(bool bNightWave);
	FVector RandomEdgePoint() const;
	bool IsClear(const FVector& Point, float Radius) const;

	void HandleNightfall();
	void HandleDawn();
	void UpdateSky();

	UPROPERTY()
	TObjectPtr<ADirectionalLight> Sun;

	UPROPERTY()
	TObjectPtr<ASkyLight> Sky;

	UPROPERTY()
	TObjectPtr<AExponentialHeightFog> Fog;

	int32 WaveRemaining = 0;
	float WaveTimer = 0.f;
	float WandererTimer = 10.f;
	float SkyRecaptureTimer = 0.f;
};
