using System.Windows;

namespace Nikke.Simulator.Wpf
{
    /// <summary>
    /// WPF 셸 — **UI 방향 보류 상태** (DESIGN §1: UI/컴퓨트 스택은 M2 벤치 후 결정, 엔진은 UI 무지).
    /// 데이터 로딩은 App.OnStartup(StatTable/EffectTable) 이 담당. 구 데이터 로드 디버그 코드는
    /// 2026-07-08 감사에서 제거 — 대조/실행 도구는 Nikke.Simulator.Harness(콘솔)가 대체.
    /// </summary>
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();
        }
    }
}
