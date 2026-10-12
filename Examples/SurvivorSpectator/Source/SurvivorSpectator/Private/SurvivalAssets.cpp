#include "SurvivalAssets.h"

#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace SurvivalAssets
{
	UStaticMesh* Cube() { return LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")); }
	UStaticMesh* Sphere() { return LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere")); }
	UStaticMesh* Cylinder() { return LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cylinder.Cylinder")); }
	UStaticMesh* Cone() { return LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cone.Cone")); }

	UMaterialInstanceDynamic* Paint(UStaticMeshComponent* Component, const FLinearColor& Color)
	{
		if (!Component)
		{
			return nullptr;
		}

		UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
		UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(Base, Component);
		Instance->SetVectorParameterValue(TEXT("Color"), Color);
		Component->SetMaterial(0, Instance);
		return Instance;
	}
}
