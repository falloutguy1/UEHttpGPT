using UnrealBuildTool;

public class SurvivorSpectatorEditorTarget : TargetRules
{
	public SurvivorSpectatorEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V5;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_4;
		ExtraModuleNames.Add("SurvivorSpectator");
	}
}
