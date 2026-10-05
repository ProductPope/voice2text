# dictAItor na Windows – instrukcja krok po kroku

Nie musisz nic programować ani wpisywać komend. Wszystko robisz dwuklikiem.
Za pierwszym razem zajmie to ok. 15–20 minut (głównie czekanie na pobieranie).

---

## Krok 1. Zainstaluj Pythona (jednorazowo)

Python to „silnik”, na którym działa dictAItor.

1. Wejdź na **https://www.python.org/downloads/windows/**
2. Znajdź najnowszą wersję **Python 3.12** (np. „Python 3.12.10”) i kliknij
   **Windows installer (64-bit)**.
3. Uruchom pobrany plik.
4. **Ważne:** na pierwszym ekranie na dole zaznacz
   ☑ **Add python.exe to PATH**.
5. Kliknij **Install Now** i poczekaj do końca. Zamknij instalator.

> Masz już inną wersję Pythona? Nie szkodzi – zainstaluj 3.12 obok.

## Krok 2. Pobierz dictAItor

1. Będąc zalogowanym na GitHubie, otwórz ten link – pobierze się plik ZIP:
   **https://github.com/ProductPope/voice2text/archive/refs/heads/claude/brave-knuth-rn94tr.zip**
2. Otwórz folder **Pobrane**, kliknij prawym przyciskiem na pobrany plik ZIP
   → **Wyodrębnij wszystkie…**
3. Jako miejsce wpisz **`C:\dictaitor`** i kliknij **Wyodrębnij**.

   (Nie rozpakowuj do folderu synchronizowanego z OneDrive – program tworzy tysiące
   małych plików i OneDrive by się „zadławił”.)

4. W środku będzie folder o długiej nazwie (np. `voice2text-claude-brave-knuth-rn94tr`),
   a w nim folder **`windows`** z sześcioma plikami:

   | Plik | Do czego |
   |---|---|
   | `1-instaluj.bat` | instalacja (raz) |
   | `2-dyktuj.bat` | dyktowanie |
   | `3-nagraj-probki.bat` | nagranie próbek do pomiaru jakości |
   | `4-zmierz-jakosc.bat` | pomiar jakości |
   | `5-ustawienia.bat` | zmiana hasła i reguł |
| `6-aplikacja.bat` | **aplikacja w zasobniku** – skrót klawiszowy i wpisywanie prosto w okno |

## Krok 3. Zezwól na mikrofon

**Start → Ustawienia → Prywatność i zabezpieczenia → Mikrofon** i włącz:
- **Dostęp do mikrofonu**
- **Zezwalaj aplikacjom klasycznym na dostęp do mikrofonu** (na samym dole listy)

## Krok 4. Instalacja

1. Dwuklik **`1-instaluj.bat`**.
2. Jeśli Windows zapyta „Czy chcesz uruchomić ten plik?” / „System Windows chronił
   ten komputer” – kliknij **Więcej informacji → Uruchom mimo to** (lub **Uruchom**).
   To normalne dla plików pobranych z internetu.
3. Poczekaj. Zobaczysz kroki 1/4 … 4/4. Krok 4 pobiera model mowy (ok. 500 MB,
   jednorazowo) – może trwać kilka minut.
4. Na końcu powinno być coś w stylu:

   ```
   Gotowe: small działa na procesorze.
   Mikrofon: Mikrofon (Realtek Audio)
   Gotowe! Teraz uruchom 2-dyktuj.bat
   ```

   Zapisz sobie, jaki model i „procesor”/„karta graficzna” się pojawiły.

## Krok 5. Pierwsze dyktowanie

1. Dwuklik **`2-dyktuj.bat`**. Poczekaj, aż pojawi się „Słucham.”
2. Powiedz normalnie, np.:

   > „Cześć Ania … spotkanie przesuwamy na czwartek … nowa linia … pozdrawiam”

3. Zrób krótką pauzę i powiedz hasło: **„wyślij teraz”** – i zamilknij na chwilę.
4. Pojawi się **✔ WYSŁANO (skopiowano do schowka)**.
5. Przejdź do dowolnego okna (mail, Slack, Claude Code) i wklej **Ctrl+V**.

Na razie tekst trafia do **schowka** – wpisywanie prosto w okno przyjdzie
z aplikacją w zasobniku (kolejny etap).

**Przydatne komendy głosowe**

| Powiedz | Efekt |
|---|---|
| „wyślij teraz” + pauza | wysyła (kopiuje do schowka) |
| „anuluj wszystko” + pauza | kasuje szkic, nic nie wysyła |
| „cofnij” | usuwa fragment od ostatniej pauzy |
| „kropka”, „przecinek”, „znak zapytania” | interpunkcja |
| „nowa linia”, „nowy akapit” | nowy wiersz |

Zakończenie: zamknij okno albo naciśnij **Ctrl+C**. Niewysłany szkic **nie** jest
nigdzie wysyłany.

## Krok 5b. Aplikacja w zasobniku (wygodniejsza)

1. Dwuklik **`6-aplikacja.bat`**. Nie pojawi się żadne okno – w prawym dolnym rogu,
   przy zegarze, pojawi się **kółko** (jeśli go nie widać, kliknij strzałkę **^**).
   Szare = ładuje model, ciemne = gotowy.
2. Kliknij tam, gdzie chcesz pisać (np. okno Slacka albo Claude Code).
3. Naciśnij **Ctrl+Alt+D** – kółko zrobi się **czerwone**, a na dole ekranu pojawi się
   okienko z tym, co mówisz.
4. Powiedz wiadomość, a potem **„wyślij teraz”**. Kółko zrobi się pomarańczowe:
   masz **0,8 sekundy**, żeby nacisnąć **Esc**, jeśli się rozmyślisz.
5. Tekst zostanie **wpisany w okno, w którym byłeś**. Program nie naciska Entera –
   wysłanie wiadomości zostaje po Twojej stronie.

Dobrze wiedzieć:
- Ponowne **Ctrl+Alt+D** w trakcie = przerwij bez wysyłania (szkic odzyskasz z menu
  pod prawym przyciskiem na kółku).
- Jeśli w międzyczasie klikniesz inne okno, tekst **nie** zostanie wpisany gdzie indziej –
  trafi do schowka (Ctrl+V).
- Wielowierszowy tekst jest wklejany, nie „wpisywany”, żeby nowa linia nie wysłała
  wiadomości w połowie.
- Zakończenie: prawy przycisk na kółku → **Zakończ**.

**Uczenie się Twoich zasad – Ctrl+Alt+K („popraw ostatni”)**

Jeśli wpisany tekst nie jest taki, jak chciałeś (np. „postgres” zamiast „PostgreSQL”,
brakujący przecinek, zła kropka po pauzie):
1. Naciśnij **Ctrl+Alt+K** – otworzy się okienko z ostatnio wpisanym tekstem.
2. Popraw go tak, jak powinien wyglądać.
3. Kliknij **Zapamiętaj** (albo **Zapamiętaj i skopiuj**, jeśli chcesz wkleić poprawioną wersję).

dictAItor zapamięta różnice. Tę samą poprawkę słowa po **2 razach** robi już sam,
a z poprawek interpunkcji uczy się, jak długie są Twoje pauzy „na zastanowienie”,
a jak długie – na koniec zdania. Listę tego, czego się nauczył (z możliwością usuwania,
eksportu i importu), znajdziesz w menu kółka: **Czego się nauczyłem…**

**Ustawienia bez Notatnika**

Prawy przycisk na kółku → **Ustawienia…**: hasło (z przyciskiem **Sprawdź hasło…** –
powiesz je 3 razy, a program pokaże, czy dobrze je słyszy), skróty, czas na Esc,
sposób wpisywania, model mowy i **uruchamianie razem z Windows**.
Po zapisaniu program zapyta o ponowne uruchomienie.

## Krok 6. Zmiana hasła i własnych reguł (opcjonalnie)

Dwuklik **`5-ustawienia.bat`** – otworzy się Notatnik z ustawieniami. Najważniejsze:

```toml
[gate]
send_phrase = "wyślij teraz"      # tu wpisz swoje hasło

[rules]
replacements = { "kubernetis" = "Kubernetes" }   # co Whisper słyszy → co ma być napisane
vocabulary = ["Kubernetes", "Marcin"]            # nazwy, które ma lepiej rozpoznawać
```

Zapisz (**Ctrl+S**) i uruchom `2-dyktuj.bat` ponownie.

## Krok 7. Pomiar jakości (ok. 20 minut) – to mi najbardziej pomoże

1. Dwuklik **`3-nagraj-probki.bat`**.
2. Wpisz krótką nazwę (np. `slack1`) i Enter.
3. Powiedz wiadomość **tak jak zwykle**, razem z hasłem na końcu. Naciśnij **Enter**.
4. Program zapyta, **co powinno zostać wysłane** – wpisz poprawny tekst
   (dokładnie tak, jak chciałbyś, żeby wyglądał). Enter.
5. Odpowiedz **T**, żeby nagrać kolejną. Zrób **20–30** próbek, różnych:
   krótkie i długie, z pauzami „na zastanowienie”, z angielskimi słowami,
   z poprawkami („w poniedziałek… nie, we wtorek”).
6. Zrób też 2–3 **podchwytliwe**: powiedz hasło *w środku* zdania
   („powiedz mu wyślij teraz raport”) – wtedy przy pytaniu „co powinno zostać wysłane”
   zostaw puste i naciśnij Enter (= nic nie powinno zostać wysłane).
7. Na koniec dwuklik **`4-zmierz-jakosc.bat`**. Wynik pojawi się na ekranie i w pliku
   **`wynik-pomiaru.txt`** – wklej mi jego zawartość.

Nagrania zostają tylko na Twoim komputerze (folder `nagrania`).

## Gdy coś nie działa

| Objaw | Co zrobić |
|---|---|
| „Nie znalazłem Pythona 3.11 lub nowszego” | Wróć do kroku 1, pamiętaj o ☑ *Add python.exe to PATH*. Po instalacji zamknij i otwórz okno ponownie. |
| „nie widzę mikrofonu” | Krok 3; sprawdź też, czy mikrofon działa np. w Rejestratorze głosu. |
| Nic się nie dzieje, gdy mówię | Mów chwilę dłużej i wyraźniej; sprawdź w **Ustawienia → System → Dźwięk**, który mikrofon jest domyślny. |
| Hasło nie działa | Po haśle zrób wyraźną pauzę (ok. 1 s). Jeśli Whisper je przekręca, zmień hasło na dłuższe/wyraźniejsze (krok 6). |
| Okno się zamknęło z błędem | Uruchom plik jeszcze raz, zrób zrzut ekranu (**Win+Shift+S**) i mi go wyślij. |
| „Karta graficzna niedostępna… używam procesora” | To tylko informacja – działa, tylko wolniej. Obsługę karty dołożymy później. |
