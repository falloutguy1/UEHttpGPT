using System.IO;
using UnrealBuildTool;

public class SurvivorSpectator : ModuleRules
{
	public SurvivorSpectator(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine", "InputCore", "AIModule", "Json", "JsonUtilities"
		});

		// The GPT-driven leader brain is optional: it is compiled in only when the HttpGPT plugin
		// sits in this project's Plugins folder. Without it the leader uses its rule-based brain.
		if (Directory.Exists(Path.GetFullPath(Path.Combine(ModuleDirectory, "..", "..", "Plugins", "HttpGPT"))))
		{
			PrivateDependencyModuleNames.AddRange(new string[] { "HttpGPTCommonModule", "HttpGPTChatModule" });
			PublicDefinitions.Add("WITH_HTTPGPT=1");
		}
		else
		{
			PublicDefinitions.Add("WITH_HTTPGPT=0");
		}
	}
}
