using System;
using System.Linq;
using System.Windows;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using System.Diagnostics; // 디버그 출력을 위해 추가!

namespace Nikke.Simulator.Wpf
{
    public partial class MainWindow : Window
    {
        public MainWindow()
        {
            InitializeComponent();

            // 앱이 켜지자마자 데이터 로드 테스트를 시작한다!
            Loaded += OnWindowLoaded;
        }

        private void OnWindowLoaded(object sender, RoutedEventArgs e)
        {
            try
            {
                // 1. 스마트 경로 탐색기로 JSON 파일 찾기
                // 이 메서드는 네가 알려준 'Database/processed/' 경로를 역추적해! ♥
                string dbPath = JsonProvider.GetSmartDatabasePath("nikke_merged_db_returned.json");

                // 2. JSON 로드 (RootDto 타입으로 찰떡같이 파싱!)
                var db = JsonProvider.LoadJson<RootDto>(dbPath);

                // 3. 데이터 로드 확인 (스노우 화이트 "5012" 출동!)
                if (db != null && db.roster.TryGetValue("5012", out var snowWhite))
                {
                    // 비주얼 스튜디오 하단 [출력] 창에 찍힐 거야!
                    Debug.WriteLine("-----------------------------------------");
                    Debug.WriteLine($"[성공] 데이터 로드 완료: {snowWhite.slug}");
                    Debug.WriteLine($"Synchro Level: {db.global_state.synchro_level}");
                    Debug.WriteLine($"Snow White User Level: {snowWhite.user.level}");

                    // 4. 오버로드 계산기 테스트 (StatAtk 기준)
                    //    2026-04-23 Option D 리팩토링: CalculatePercentBonus → CalculateFinalBaseStat 로 API 전환.
                    //    (소비자가 nativeStat + OL 합산을 직접 얻을 수 있도록 반환값이 이미 더해진 최종치가 되었음.)
                    double testNativeAtk = 25000;
                    var olAtkPercents = snowWhite.user.overload_stats
                        .Where(o => o.type == "StatAtk")
                        .Select(o => o.value);
                    double finalAtk = OverloadProcessor.CalculateFinalBaseStat(
                        testNativeAtk, olAtkPercents, 0, 0);
                    double olAtkBonus = finalAtk - testNativeAtk;

                    Debug.WriteLine($"테스트 공격력: {testNativeAtk}");
                    Debug.WriteLine($"오버로드 공격력 보너스: {olAtkBonus}");
                    Debug.WriteLine($"최종 연산 결과: {finalAtk}");
                    Debug.WriteLine("-----------------------------------------");

                    MessageBox.Show($"{snowWhite.slug} 데이터를 성공적으로 불러왔어, 허접군! ♥\n출력 창을 확인해봐!", "가키짱의 축복");
                }
                else
                {
                    MessageBox.Show("데이터는 읽었는데 스노우 화이트(5012)가 없어... 네가 JSON 수정한 거 아니지?", "경고");
                }
            }
            catch (Exception ex)
            {
                // 에러 발생 시 아주 친절하게(?) 욕해줌
                Debug.WriteLine($"[ERROR] {ex.Message}");
                MessageBox.Show($"에러 발생! 역시 허접군이야♥\n내용: {ex.Message}", "에러");
            }
        }
    }
}