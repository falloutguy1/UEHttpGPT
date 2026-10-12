using UnrealBuildTool;

public class SurvivorSpectatorTarget : TargetRules
{
	public SurvivorSpectatorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_4;
		ExtraModuleNames.Add("SurvivorSpectator");
	}
}
