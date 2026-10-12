#include "SurvivalPlayerController.h"

#include "Kismet/GameplayStatics.h"
#include "SurvivalGameState.h"
#include "SurvivalSpectatorPawn.h"
#include "SurvivorCharacter.h"

namespace
{
	const float SpeedSteps[] = {0.25f, 0.5f, 1.f, 2.f, 4.f, 8.f};
}

ASurvivalPlayerController::ASurvivalPlayerController()
{
	bShowMouseCursor = false;
}

void ASurvivalPlayerController::BeginPlay()
{
	Super::BeginPlay();
	SetInputMode(FInputModeGameOnly());
	SetControlRotation(FRotator(-25.f, 45.f, 0.f));
}

ASurvivalSpectatorPawn* ASurvivalPlayerController::SpectatorPawn() const
{
	return Cast<ASurvivalSpectatorPawn>(GetPawn());
}

float ASurvivalPlayerController::GetTimeScale() const
{
	return IsPaused() ? 0.f : SpeedSteps[SpeedStep];
}

void ASurvivalPlayerController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);

	ASurvivalSpectatorPawn* Cam = SpectatorPawn();
	const ASurvivalGameState* GS = GetWorld()->GetGameState<ASurvivalGameState>();
	if (!Cam || !GS)
	{
		return;
	}

	// Mouse look.
	float DX = 0.f, DY = 0.f;
	GetInputMouseDelta(DX, DY);
	AddYawInput(DX);
	AddPitchInput(-DY);

	HandleKeys();

	// Leader mode keeps the camera on whoever currently leads, even after a succession.
	if (bFollowLeader)
	{
		if (ASurvivorCharacter* Leader = GS->GetLeader())
		{
			if (Watched.Get() != Leader)
			{
				Watch(Leader, true);
			}
		}
	}
	else if (!Watched.IsValid() && GS->Survivors.Num() > 0)
	{
		Watch(GS->Survivors[0], false);
	}

	if (Cam->GetMode() == ESpectateMode::Free)
	{
		Cam->FlyInput = FVector((IsInputKeyDown(EKeys::W) ? 1.f : 0.f) - (IsInputKeyDown(EKeys::S) ? 1.f : 0.f),
		                        (IsInputKeyDown(EKeys::D) ? 1.f : 0.f) - (IsInputKeyDown(EKeys::A) ? 1.f : 0.f),
		                        (IsInputKeyDown(EKeys::E) ? 1.f : 0.f) - (IsInputKeyDown(EKeys::Q) ? 1.f : 0.f));
		Cam->bFastFly = IsInputKeyDown(EKeys::LeftShift);
	}
	else
	{
		Cam->FlyInput = FVector::ZeroVector;
	}
}

void ASurvivalPlayerController::HandleKeys()
{
	ASurvivalSpectatorPawn* Cam = SpectatorPawn();
	const ASurvivalGameState* GS = GetWorld()->GetGameState<ASurvivalGameState>();

	auto Pressed = [this](const FKey& Key) { return WasInputKeyJustPressed(Key); };

	// Pick who to watch.
	if (Pressed(EKeys::Tab) || Pressed(EKeys::Right))
	{
		CycleWatched(IsInputKeyDown(EKeys::LeftShift) ? -1 : 1);
	}
	if (Pressed(EKeys::Left))
	{
		CycleWatched(-1);
	}
	const FKey NumberKeys[] = {EKeys::One, EKeys::Two, EKeys::Three, EKeys::Four, EKeys::Five, EKeys::Six, EKeys::Seven, EKeys::Eight};
	for (int32 i = 0; i < UE_ARRAY_COUNT(NumberKeys); ++i)
	{
		if (Pressed(NumberKeys[i]) && GS->Survivors.IsValidIndex(i))
		{
			Watch(GS->Survivors[i], false);
		}
	}
	if (Pressed(EKeys::L))
	{
		bFollowLeader = true;
	}

	// Camera modes.
	if (Pressed(EKeys::C))
	{
		Cam->SetMode(ESpectateMode::Follow);
	}
	if (Pressed(EKeys::T))
	{
		Cam->SetMode(Cam->GetMode() == ESpectateMode::Tactical ? ESpectateMode::Follow : ESpectateMode::Tactical);
	}
	if (Pressed(EKeys::F))
	{
		Cam->SetMode(Cam->GetMode() == ESpectateMode::Free ? ESpectateMode::Follow : ESpectateMode::Free);
	}
	if (Pressed(EKeys::MouseScrollUp))
	{
		Cam->Zoom(-80.f);
	}
	if (Pressed(EKeys::MouseScrollDown))
	{
		Cam->Zoom(80.f);
	}

	// Game speed.
	if (Pressed(EKeys::RightBracket) || Pressed(EKeys::Add))
	{
		SetSpeedStep(SpeedStep + 1);
	}
	if (Pressed(EKeys::LeftBracket) || Pressed(EKeys::Subtract))
	{
		SetSpeedStep(SpeedStep - 1);
	}
	if (Pressed(EKeys::SpaceBar) || Pressed(EKeys::P))
	{
		SetPause(!IsPaused());
	}

	// Interface.
	if (Pressed(EKeys::H))
	{
		bShowHud = !bShowHud;
	}
	if (Pressed(EKeys::F1))
	{
		bShowHelp = !bShowHelp;
	}
	if (Pressed(EKeys::R) && GS->bGameOver)
	{
		UGameplayStatics::SetGlobalTimeDilation(this, 1.f);
		ConsoleCommand(TEXT("RestartLevel"));
	}
	if (Pressed(EKeys::Escape))
	{
		ConsoleCommand(TEXT("quit"));
	}
}

void ASurvivalPlayerController::Watch(ASurvivorCharacter* Survivor, bool bLeaderMode)
{
	Watched = Survivor;
	bFollowLeader = bLeaderMode;
	if (ASurvivalSpectatorPawn* Cam = SpectatorPawn())
	{
		Cam->SetFollowTarget(Survivor);
	}
}

void ASurvivalPlayerController::CycleWatched(int32 Direction)
{
	const ASurvivalGameState* GS = GetWorld()->GetGameState<ASurvivalGameState>();
	const int32 Count = GS->Survivors.Num();
	if (Count == 0)
	{
		return;
	}
	int32 Index = GS->Survivors.IndexOfByKey(Watched.Get());
	// Skip the dead unless everyone is.
	for (int32 Step = 0; Step < Count; ++Step)
	{
		Index = (Index + Direction + Count) % Count;
		if (GS->Survivors[Index] && !GS->Survivors[Index]->IsDead())
		{
			break;
		}
	}
	Watch(GS->Survivors[Index], false);
}

void ASurvivalPlayerController::SetSpeedStep(int32 Step)
{
	SpeedStep = FMath::Clamp(Step, 0, static_cast<int32>(UE_ARRAY_COUNT(SpeedSteps)) - 1);
	UGameplayStatics::SetGlobalTimeDilation(this, SpeedSteps[SpeedStep]);
}
