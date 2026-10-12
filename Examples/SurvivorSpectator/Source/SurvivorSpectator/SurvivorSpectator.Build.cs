using UnrealBuildTool;

public class SurvivorSpectator : ModuleRules
{
	public SurvivorSpectator(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine", "InputCore", "AIModule", "Json"
		});

		// HttpGPT is this repository's own plugin; the .uproject finds it two folders up.
		PrivateDependencyModuleNames.AddRange(new string[] { "HttpGPTCommonModule", "HttpGPTChatModule" });
	}
}
