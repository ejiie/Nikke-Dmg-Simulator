using System.Configuration;
using System.Data;
using System.Windows;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Stats;

namespace Nikke.Simulator.Wpf;

/// <summary>
/// Interaction logic for App.xaml
/// </summary>
public partial class App : Application
{
    /// <summary>
    /// 앱 시작 시 1회 호출. StatTable 같은 정적 룩업 테이블은 여기서 로드해야
    /// 이후 MainWindow / ViewModel / Nikke 엔티티에서 0값으로 계산되는 사고를 막는다.
    /// </summary>
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        try
        {
            // Database/processed/stat_table.csv — worktree 루트에서 스마트 탐색
            string csvPath = JsonProvider.GetSmartDatabasePath("stat_table.csv");
            StatTable.Initialize(csvPath);

            // 장비 base 표 (blablalink ItemEquipTable). 없으면 장비 스탯 0으로 동작.
            try
            {
                string equipPath = JsonProvider.GetSmartDatabasePath("equip_stat_table.json");
                StatTable.InitializeEquipment(equipPath);
            }
            catch (System.Exception) { /* 장비 표 없으면 스킵(0) */ }

            // 큐브/소장품 공식 특수효과 표 (enum/dict). 없으면 해당 효과 0.
            try
            {
                Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCube(
                    JsonProvider.GetSmartDatabasePath("cube_effect_table.json"));
            }
            catch (System.Exception) { }
            try
            {
                Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCollection(
                    JsonProvider.GetSmartDatabasePath("collection_effect_table.json"));
            }
            catch (System.Exception) { }
        }
        catch (System.Exception ex)
        {
            MessageBox.Show(
                $"StatTable 초기화 실패로 앱을 종료합니다.\n\n" +
                $"원인: {ex.Message}\n\n" +
                $"확인: Database/processed/stat_table.csv 존재 여부 및 포맷.",
                "초기화 에러",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(1);
        }
    }
}

