// ==========================================
// Zennoposter — Bohemia Interactive Parser v2.0
// Парсит @bohemiainteract, фильтрует DayZ-контент
// с высоким охватом, отправляет на веб-панель
// ==========================================

string webPanelUrl = "https://dayz-monitor-web.vercel.app";
string botApiKey = "YOUR_BOT_API_KEY_HERE";
string stateFile = project.Directory + "\\twitter_bohemia_state.txt";
string targetHandle = "bohemiainteract";
string profileUrl = "https://x.com/" + targetHandle;
int scrollCount = 5;            // Скроллов вниз — больше твитов
int pageLoadMs = 15000;
int scrollDelayMs = 2500;
int reactDelayMs = 3000;
int minLikes = 10;              // Минимум лайков для поста без слова DayZ
int maxTweets = 30;             // Макс твитов для проверки

// ---- Логирование ----

void LogInfo(string msg) {
    try {
        project.SendInfoToLog(msg, "BohemiaParser", true);
        string logDir = project.Directory + "\\logs";
        if (!System.IO.Directory.Exists(logDir)) System.IO.Directory.CreateDirectory(logDir);
        string logFile = logDir + "\\bohemia_parser_" + DateTime.Now.ToString("yyyy-MM-dd") + ".txt";
        string line = "[" + DateTime.Now.ToString("HH:mm:ss") + "] " + msg + "\r\n";
        ZennoLab.Macros.FileSystem.FileAppendString(logFile, line, true);
    } catch {}
}

void LogError(string msg, Exception ex) {
    try {
        string err = (ex != null) ? ex.Message : "no error";
        project.SendErrorToLog(msg + ": " + err, "BohemiaParser", true);
        string logDir = project.Directory + "\\logs";
        if (!System.IO.Directory.Exists(logDir)) System.IO.Directory.CreateDirectory(logDir);
        string logFile = logDir + "\\bohemia_parser_errors_" + DateTime.Now.ToString("yyyy-MM-dd") + ".txt";
        string line = "[" + DateTime.Now.ToString("HH:mm:ss") + "] " + msg + ": " + (ex != null ? ex.ToString() : "") + "\r\n";
        ZennoLab.Macros.FileSystem.FileAppendString(logFile, line, true);
    } catch {}
}

string EscapeJson(string s) {
    if (string.IsNullOrEmpty(s)) return "";
    return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
}

// ---- Работа с состоянием ----

void SavePostedIds(System.Collections.Generic.HashSet<string> ids) {
    try {
        string dir = System.IO.Path.GetDirectoryName(stateFile);
        if (!System.IO.Directory.Exists(dir)) System.IO.Directory.CreateDirectory(dir);
        string[] arr = new string[ids.Count];
        ids.CopyTo(arr);
        System.IO.File.WriteAllLines(stateFile, arr);
    } catch (Exception ex) {
        LogError("Ошибка сохранения state", ex);
    }
}

System.Collections.Generic.HashSet<string> LoadPostedIds() {
    var ids = new System.Collections.Generic.HashSet<string>();
    try {
        if (System.IO.File.Exists(stateFile)) {
            string[] lines = System.IO.File.ReadAllLines(stateFile);
            foreach (string line in lines) {
                string id = line.Trim();
                if (!string.IsNullOrEmpty(id)) ids.Add(id);
            }
        }
    } catch (Exception ex) {
        LogError("Ошибка загрузки state", ex);
    }
    return ids;
}

// ---- Отправка на веб-панель ----

bool SendToPanel(string tweetId, string tweetText, string tweetUrl, string imageUrl, int likes, bool isDayZ) {
    try {
        string safeText = EscapeJson(tweetText);
        if (safeText.Length > 2000) safeText = safeText.Substring(0, 2000);

        string imagesJson = "[]";
        if (!string.IsNullOrEmpty(imageUrl)) {
            imagesJson = "[\"" + EscapeJson(imageUrl) + "\"]";
        }

        // Приоритет high для DayZ контента с картинками
        string priority = "medium";
        if (isDayZ && !string.IsNullOrEmpty(imageUrl)) priority = "high";
        else if (isDayZ) priority = "medium";
        else if (likes >= 500) priority = "medium";

        string body = "{" +
            "\"sourceId\":\"twitter\"," +
            "\"externalId\":\"" + EscapeJson(tweetId) + "\"," +
            "\"serverName\":\"X/Twitter @bohemiainteract\"," +
            "\"content\":\"" + safeText + "\"," +
            "\"summary\":\"\"," +
            "\"formattedPost\":\"\"," +
            "\"newsType\":\"content\"," +
            "\"priority\":\"" + priority + "\"," +
            "\"images\":" + imagesJson +
        "}";

        string apiUrl = webPanelUrl + "/api/news";
        string response = ZennoPoster.HTTP.Request(
            ZennoLab.InterfacesLibrary.Enums.Http.HttpMethod.POST,
            apiUrl,
            body
        );

        if (!string.IsNullOrEmpty(response) && (response.Contains("\"news_id\"") || response.Contains("\"success\":true"))) {
            LogInfo("  -> Отправлен: " + tweetId + " (priority=" + priority + ")");
            return true;
        } else {
            LogInfo("  -> Ответ: " + (response.Length > 200 ? response.Substring(0, 200) : response));
            return false;
        }
    } catch (Exception ex) {
        LogError("Ошибка отправки", ex);
        return false;
    }
}

// ---- Парсинг числа из текста ----
// "1,234" -> 1234, "5.2K" -> 5200, "10M" -> 10000000

int ParseCount(string s) {
    if (string.IsNullOrEmpty(s)) return 0;
    s = s.Trim();
    double mult = 1;
    if (s.EndsWith("K") || s.EndsWith("k")) { mult = 1000; s = s.Substring(0, s.Length - 1); }
    else if (s.EndsWith("M") || s.EndsWith("m")) { mult = 1000000; s = s.Substring(0, s.Length - 1); }
    s = s.Replace(",", "").Replace(".", "").Trim();
    double val;
    if (double.TryParse(s, System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out val)) {
        return (int)(val * mult);
    }
    return 0;
}

// ---- Парсинг твитов из HTML ----

System.Collections.Generic.List<string[]> ParseTweetsFromHtml(string html) {
    var tweets = new System.Collections.Generic.List<string[]>();
    // string[] = {id, text, url, imageUrl, isReply, isDayZ, likes}

    var articleMatches = System.Text.RegularExpressions.Regex.Matches(
        html,
        @"<article[^>]*data-testid=""tweet""[^>]*>(.*?)</article>",
        System.Text.RegularExpressions.RegexOptions.Singleline
    );

    LogInfo("Найдено article блоков: " + articleMatches.Count);

    for (int a = 0; a < articleMatches.Count && a < maxTweets; a++) {
        try {
            string ah = articleMatches[a].Groups[1].Value;

            // --- Tweet ID и URL ---
            string tweetId = "";
            string tweetUrl = "";
            var linkMatch = System.Text.RegularExpressions.Regex.Match(
                ah, @"href=""(https?://[^""]*?/status/(\d+)[^""]*?)"""
            );
            if (linkMatch.Success) {
                tweetUrl = linkMatch.Groups[1].Value;
                tweetId = linkMatch.Groups[2].Value;
            }
            if (string.IsNullOrEmpty(tweetId)) continue;

            // --- Текст твита ---
            string tweetText = "";
            var textMatch = System.Text.RegularExpressions.Regex.Match(
                ah,
                @"data-testid=""tweetText""[^>]*>(.*?)</div>",
                System.Text.RegularExpressions.RegexOptions.Singleline
            );
            if (textMatch.Success) {
                tweetText = textMatch.Groups[1].Value;
                tweetText = System.Text.RegularExpressions.Regex.Replace(tweetText, @"<[^>]+>", " ");
                tweetText = tweetText.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&amp;", "&").Replace("&quot;", "\"");
                tweetText = System.Text.RegularExpressions.Regex.Replace(tweetText, @"\s+", " ").Trim();
            }

            // --- Картинка ---
            string imageUrl = "";
            var imgMatch = System.Text.RegularExpressions.Regex.Match(
                ah, @"src=""(https://pbs\.twimg\.com/media/[^""]+)"""
            );
            if (imgMatch.Success) {
                imageUrl = imgMatch.Groups[1].Value;
                imageUrl = System.Text.RegularExpressions.Regex.Replace(imageUrl, @"\?.*$", "?format=jpg&name=large");
            }

            // --- Видео: poster image (не media/, а profile_images или pic/) ---
            bool hasVideo = ah.Contains("data-testid=\"videoPlayer\"") || ah.Contains("videoContainer");

            // --- Лайки ---
            int likes = 0;
            // Ищем блок с лайками: aria-label содержит "Like" и число
            // Формат: aria-label="123 Likes" или "1.2K Likes"
            var likeMatches = System.Text.RegularExpressions.Regex.Matches(
                ah, @"aria-label=""([\d.,\s]*[KkMm]?\d*)\s*[Ll]ike"""
            );
            if (likeMatches.Count > 0) {
                likes = ParseCount(likeMatches[0].Groups[1].Value);
            }
            // Fallback: data-testid="like" рядом с числом
            if (likes == 0) {
                var likeBlock = System.Text.RegularExpressions.Regex.Match(
                    ah, @"data-testid=""like""[^>]*>.*?<span[^>]*>(\d[\d.,\s]*[KkMm]?\d*)</span>",
                    System.Text.RegularExpressions.RegexOptions.Singleline
                );
                if (likeBlock.Success) {
                    likes = ParseCount(likeBlock.Groups[1].Value);
                }
            }

            // --- Ретвиты ---
            int retweets = 0;
            var rtMatches = System.Text.RegularExpressions.Regex.Matches(
                ah, @"aria-label=""([\d.,\s]*[KkMm]?\d*)\s*[Rr]epost"""
            );
            if (rtMatches.Count > 0) {
                retweets = ParseCount(rtMatches[0].Groups[1].Value);
            }

            // --- Реплай ---
            bool isReply = ah.Contains("Replying to");

            // --- Содержит "DayZ"? ---
            bool isDayZ = System.Text.RegularExpressions.Regex.IsMatch(tweetText + " " + imageUrl, @"DayZ", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

            // === ФИЛЬТРАЦИЯ ===
            // Пропускаем: реплаи, ретвиты без текста
            if (isReply) continue;

            string cleanText = System.Text.RegularExpressions.Regex.Replace(tweetText, @"https?://\S+", "").Trim();

            // Фильтр: оставляем только если:
            // 1) Содержит "DayZ" в тексте или картинке
            // 2) ИЛИ есть картинка/видео И высокая вовлечённость (лайки + ретвиты >= minLikes)
            bool isPopular = (likes + retweets) >= minLikes;
            bool hasMedia = !string.IsNullOrEmpty(imageUrl) || hasVideo;

            if (!isDayZ && !hasMedia && !isPopular) continue;  // Мало лайков даже с картинкой — не интересно

            tweets.Add(new string[] {
                tweetId, tweetText, tweetUrl, imageUrl,
                isReply ? "1" : "0",
                isDayZ ? "1" : "0",
                likes.ToString()
            });

            LogInfo("  Кандидат #" + tweetId + " | DayZ=" + isDayZ + " | likes=" + likes + " RT=" + retweets + " | img=" + (!string.IsNullOrEmpty(imageUrl) ? "yes" : "no") + " | reply=" + isReply + " | text=" + (tweetText.Length > 80 ? tweetText.Substring(0, 80) + "..." : tweetText));

        } catch {}
    }

    return tweets;
}

// ---- Проверка на блокировку / логин ----

bool IsLoginRequired() {
    try {
        string pageText = instance.ActiveTab.DomText ?? "";
        string pageUrl = instance.ActiveTab.URL ?? "";

        if (pageText.Contains("Sign in to X") || pageText.Contains("Log in to X") ||
            (pageText.Contains("Sign in") && pageText.Contains("password"))) return true;
        if (pageUrl.Contains("/login") || pageUrl.Contains("/i/flow/login")) return true;
        if (pageText.Contains("Something went wrong") || pageText.Contains("Rate limit exceeded")) return true;
        return false;
    } catch { return false; }
}

// ==========================================
//  ОСНОВНАЯ ЛОГИКА
// ==========================================

LogInfo("==========================================");
LogInfo("Bohemia Interactive Parser v2.0 — ЗАПУСК");
LogInfo("Цель: @bohemiainteract | DayZ + популярное");
LogInfo("==========================================");

var postedIds = LoadPostedIds();
LogInfo("Загружено " + postedIds.Count + " отправленных ID");

// Навигация
LogInfo("Открываю " + profileUrl + " ...");
instance.ActiveTab.Navigate(profileUrl);
instance.ActiveTab.WaitDownloading();
System.Threading.Thread.Sleep(reactDelayMs);

if (IsLoginRequired()) {
    LogInfo("ТРЕБУЕТСЯ АВТОРИЗАЦИЯ! Залогинись в X вручную.");
    throw new Exception("Требуется авторизация в X/Twitter");
}

LogInfo("Жду загрузки...");
System.Threading.Thread.Sleep(pageLoadMs);

// Скролл
for (int s = 0; s < scrollCount; s++) {
    try {
        instance.ActiveTab.Navigate("javascript:void(window.scrollBy(0,1500))");
        LogInfo("Скролл " + (s + 1) + "/" + scrollCount);
        System.Threading.Thread.Sleep(scrollDelayMs);
    } catch {}
}
System.Threading.Thread.Sleep(reactDelayMs);

// Получаем HTML
LogInfo("Получаю HTML...");
string pageHtml = "";
try {
    HtmlElement body = instance.ActiveTab.FindElementByXPath("//body", 0);
    if (body != null) pageHtml = body.InnerHtml ?? "";
} catch (Exception ex) {
    LogError("Не получил HTML", ex);
}

if (string.IsNullOrEmpty(pageHtml)) {
    pageHtml = instance.ActiveTab.DomText ?? "";
}

LogInfo("HTML длина: " + pageHtml.Length);

// Парсинг
var allTweets = ParseTweetsFromHtml(pageHtml);
LogInfo("Подходящих твитов: " + allTweets.Count);

// Отправка
int newCount = 0;
int sentCount = 0;

foreach (string[] td in allTweets) {
    string tweetId = td[0];
    string tweetText = td[1];
    string tweetUrl = td[2];
    string imageUrl = td[3];
    bool isDayZ = td[5] == "1";
    int likes = 0;
    int.TryParse(td[6], out likes);

    if (postedIds.Contains(tweetId)) continue;
    newCount++;

    string tag = isDayZ ? "[DAYZ]" : "[POPULAR]";
    LogInfo(tag + " #" + tweetId + " likes=" + likes + " — " + (tweetText.Length > 60 ? tweetText.Substring(0, 60) + "..." : tweetText));
    if (!string.IsNullOrEmpty(imageUrl)) LogInfo("  Img: " + imageUrl);

    bool ok = SendToPanel(tweetId, tweetText, tweetUrl, imageUrl, likes, isDayZ);
    if (ok) sentCount++;

    postedIds.Add(tweetId);
    System.Threading.Thread.Sleep(1500);
}

SavePostedIds(postedIds);

if (postedIds.Count > 500) {
    var keep = new System.Collections.Generic.List<string>(postedIds);
    keep.RemoveRange(0, keep.Count - 500);
    postedIds = new System.Collections.Generic.HashSet<string>(keep);
    SavePostedIds(postedIds);
}

LogInfo("==========================================");
LogInfo("ИТОГО: новых " + newCount + " | отправлено " + sentCount);
LogInfo("==========================================");