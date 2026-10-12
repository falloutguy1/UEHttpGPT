#pragma once

#include "CoreMinimal.h"

class UStaticMesh;
class UStaticMeshComponent;
class UMaterialInstanceDynamic;

/** Everything in the game is built from the engine's basic shapes, so the project needs no content assets. */
namespace SurvivalAssets
{
	SURVIVORSPECTATOR_API UStaticMesh* Cube();
	SURVIVORSPECTATOR_API UStaticMesh* Sphere();
	SURVIVORSPECTATOR_API UStaticMesh* Cylinder();
	SURVIVORSPECTATOR_API UStaticMesh* Cone();

	/** Gives the component a dynamic instance of BasicShapeMaterial tinted with Color. */
	SURVIVORSPECTATOR_API UMaterialInstanceDynamic* Paint(UStaticMeshComponent* Component, const FLinearColor& Color);
}
