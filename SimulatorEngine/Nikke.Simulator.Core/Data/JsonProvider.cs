using System;
using System.IO;
using System.Text.Json;

namespace Nikke.Simulator.Core.Data
{
    public static class JsonProvider
    {
        private static readonly JsonSerializerOptions _options = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            AllowTrailingCommas = true
        };

        /// <summary>
        /// 현재 실행 위치(bin/Debug/...)로부터 상위 디렉터리를 거슬러 올라가며
        /// 'Database' 폴더를 찾아, Database/processed/&lt;targetFileName&gt; 의 절대 경로를 반환한다.
        /// 찾지 못하면 DirectoryNotFoundException.
        /// </summary>
        public static string GetSmartDatabasePath(string targetFileName)
        {
            if (string.IsNullOrWhiteSpace(targetFileName))
                throw new ArgumentException("targetFileName이 비어 있음.", nameof(targetFileName));

            string currentDir = AppContext.BaseDirectory;

            // [B4] DirectoryInfo.Parent 는 nullable 반환 → 변수 자체를 nullable 선언
            DirectoryInfo? dirInfo = new DirectoryInfo(currentDir);

            while (dirInfo != null && !Directory.Exists(Path.Combine(dirInfo.FullName, "Database")))
            {
                dirInfo = dirInfo.Parent;
            }

            if (dirInfo == null)
            {
                throw new DirectoryNotFoundException(
                    $"프로젝트 루트에서 'Database' 폴더를 찾지 못했습니다. " +
                    $"탐색 시작 경로: {currentDir}");
            }

            return Path.Combine(dirInfo.FullName, "Database", "processed", targetFileName);
        }

        /// <summary>
        /// JSON 파일을 타입 T로 역직렬화. T는 reference 타입이어야 한다(class 제약).
        /// 실패 케이스는 모두 구체적 예외로 bubble-up:
        ///  - 파일 없음 → FileNotFoundException
        ///  - 읽기 실패 → IOException
        ///  - JSON 파싱 실패 → JsonException (원본을 InnerException으로 체인)
        ///  - 파싱 결과가 null ('null' 리터럴 등) → InvalidDataException
        /// </summary>
        /// <typeparam name="T">역직렬화 목표 클래스 타입</typeparam>
        public static T LoadJson<T>(string filePath) where T : class
        {
            if (string.IsNullOrWhiteSpace(filePath))
                throw new ArgumentException("filePath가 비어 있음.", nameof(filePath));

            if (!File.Exists(filePath))
                throw new FileNotFoundException(
                    $"JSON 파일이 존재하지 않음: {filePath}", filePath);

            string jsonString;
            try
            {
                jsonString = File.ReadAllText(filePath);
            }
            catch (IOException ex)
            {
                // IO 실패는 원인을 InnerException 으로 보존
                throw new IOException(
                    $"JSON 파일 읽기 실패: {filePath}", ex);
            }

            // [B4] Deserialize<T> 는 T? 반환 → nullable 로 받은 뒤 명시적 null-check
            T? result;
            try
            {
                result = JsonSerializer.Deserialize<T>(jsonString, _options);
            }
            catch (JsonException ex)
            {
                throw new JsonException(
                    $"JSON 파싱 실패 ({Path.GetFileName(filePath)}): {ex.Message}",
                    ex);
            }

            if (result == null)
                throw new InvalidDataException(
                    $"JSON 파싱 결과가 null. 파일이 'null' 리터럴이거나 " +
                    $"타입 매핑 실패 가능성: {filePath}");

            return result;
        }
    }
}
