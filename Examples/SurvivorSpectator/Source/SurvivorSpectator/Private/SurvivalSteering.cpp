#include "SurvivalSteering.h"

#include "ArenaProp.h"
#include "GameFramework/Character.h"
#include "SurvivalGameState.h"
#include "SurvivorCharacter.h"
#include "ZombieCharacter.h"

namespace
{
	void AddSeparation(const FVector& Pos, const AActor* Other, const AActor* Self, FVector& Push)
	{
		if (!Other || Other == Self)
		{
			return;
		}
		const FVector Away = Pos - Other->GetActorLocation();
		const float Dist = Away.Size2D();
		if (Dist > 1.f && Dist < 110.f)
		{
			Push += Away.GetSafeNormal2D() * (1.f - Dist / 110.f);
		}
	}
}

namespace SurvivalSteering
{
	bool MoveTowards(ACharacter* Self, const FVector& Goal, float AcceptRadius)
	{
		if (!Self)
		{
			return false;
		}

		const FVector Pos = Self->GetActorLocation();
		const FVector ToGoal = Goal - Pos;
		const float Dist = ToGoal.Size2D();
		if (Dist <= AcceptRadius)
		{
			return true;
		}

		FVector Desired = ToGoal.GetSafeNormal2D();
		const ASurvivalGameState* State = Self->GetWorld()->GetGameState<ASurvivalGameState>();
		if (State)
		{
			// Slide around obstacles that sit between us and the goal.
			for (const AArenaProp* Prop : State->Obstacles)
			{
				if (!Prop)
				{
					continue;
				}
				const FVector ToProp = Prop->GetActorLocation() - Pos;
				const float Ahead = FVector::DotProduct(ToProp, Desired);
				const float Clearance = Prop->GetAvoidanceRadius() + 70.f;
				if (Ahead <= 0.f || Ahead > Clearance + 250.f || Ahead > Dist)
				{
					continue;
				}
				const FVector Lateral = ToProp - Desired * Ahead;
				const float LateralDist = Lateral.Size2D();
				if (LateralDist < Clearance)
				{
					// Steer to whichever side of the prop we're already on.
					FVector Side = -Lateral.GetSafeNormal2D();
					if (Side.IsNearlyZero())
					{
						Side = FVector::CrossProduct(Desired, FVector::UpVector);
					}
					Desired += Side * (1.5f * (1.f - LateralDist / Clearance));
				}
			}

			FVector Push = FVector::ZeroVector;
			for (const ASurvivorCharacter* Other : State->Survivors)
			{
				AddSeparation(Pos, Other, Self, Push);
			}
			for (const AZombieCharacter* Other : State->Zombies)
			{
				AddSeparation(Pos, Other, Self, Push);
			}
			Desired += Push * 0.8f;
		}

		Self->AddMovementInput(Desired.GetSafeNormal2D(), 1.f);
		return false;
	}
}
