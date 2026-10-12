#pragma once

#include "CoreMinimal.h"

class ACharacter;
class ASurvivalGameState;

/**
 * Lightweight steering so the arena works without a baked NavMesh: head for the goal,
 * slide around blocking props and keep a little personal space from other characters.
 */
namespace SurvivalSteering
{
	/** Feeds movement input toward Goal. Returns true once within AcceptRadius (2D). */
	SURVIVORSPECTATOR_API bool MoveTowards(ACharacter* Self, const FVector& Goal, float AcceptRadius);
}
