"""Сборка APK в Windows. Зависимости скачиваются только при подготовке стенда."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / ".tools"
GRADLE = "8.9"


def download(url, target):
    if not target.exists():
        print(f"Загрузка {url}", flush=True)
        partial = target.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=90) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        partial.replace(target)


def run(args, env, stdin=None):
    print("Запуск: " + " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=ROOT, env=env, input=stdin, text=True, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true", help="Скачать JDK, Gradle, Android SDK и принять лицензии Android SDK")
    parser.add_argument("--offline", action="store_true", help="Сборка из локального кеша без интернета")
    parser.add_argument("--install", action="store_true", help="Установить APK на один подключённый по USB телефон")
    parser.add_argument("--serial", help="Серийный номер adb при нескольких устройствах")
    args = parser.parse_args()
    if args.setup and args.offline:
        parser.error("--setup и --offline несовместимы")
    if os.name != "nt":
        parser.error("Этот скрипт готовит инструменты для Windows; на других ОС откройте mobile/ в Android Studio")
    TOOLS.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["GRADLE_USER_HOME"] = str(TOOLS / "gradle-cache")
    env["ANDROID_USER_HOME"] = str(TOOLS / "android-user")
    env.pop("ANDROID_PREFS_ROOT", None)
    (TOOLS / "android-user").mkdir(exist_ok=True)
    env["DEBUG"] = ""
    jdk = TOOLS / "jdk"
    gradle = TOOLS / f"gradle-{GRADLE}"
    sdk = TOOLS / "sdk"
    if args.setup:
        if not jdk.exists():
            archive = TOOLS / "jdk.zip"
            download("https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip", archive)
            with zipfile.ZipFile(archive) as z:
                folder = z.namelist()[0].split('/')[0]
                z.extractall(TOOLS)
            (TOOLS / folder).rename(jdk)
        if not gradle.exists():
            archive = TOOLS / "gradle.zip"
            download(f"https://services.gradle.org/distributions/gradle-{GRADLE}-bin.zip", archive)
            with zipfile.ZipFile(archive) as z:
                z.extractall(TOOLS)
        manager = sdk / "cmdline-tools/latest/bin/sdkmanager.bat"
        if not manager.exists():
            archive = TOOLS / "sdk.zip"
            download("https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip", archive)
            with zipfile.ZipFile(archive) as z:
                z.extractall(TOOLS / "sdk-unpack")
            manager.parent.parent.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(TOOLS / "sdk-unpack/cmdline-tools"), str(manager.parent.parent))
    if not jdk.exists() or not gradle.exists():
        sys.exit("Сначала выполните: py mobile/build.py --setup (нужен интернет)")
    env["JAVA_HOME"] = str(jdk)
    env["ANDROID_HOME"] = str(sdk)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    # Gradle копирует PATH в java.library.path: кавычки ломают запуск JVM тестов.
    path_entries = env.get("PATH", "").replace('"', '').split(os.pathsep)
    env["PATH"] = os.pathsep.join([str(jdk / "bin"), *path_entries])
    if args.setup:
        # Запускаем штатный скрипт SDK; собственные скрипты проекта — на Python.
        run(["cmd.exe", "/c", sdk / "cmdline-tools/latest/bin/sdkmanager.bat", f"--sdk_root={sdk}", "--licenses"], env, "y\n" * 100)
        run(["cmd.exe", "/c", sdk / "cmdline-tools/latest/bin/sdkmanager.bat", f"--sdk_root={sdk}", "platforms;android-35", "build-tools;35.0.0", "platform-tools"], env, "y\n" * 100)
    (ROOT / "local.properties").write_text("sdk.dir=" + sdk.as_posix() + "\n", encoding="utf-8")
    launcher = gradle / f"lib/gradle-launcher-{GRADLE}.jar"
    tasks = ["testDebugUnitTest", "lintDebug", "assembleDebug"]
    if args.offline:
        tasks.append("--offline")
    run([jdk / "bin/java.exe", "-classpath", launcher, "org.gradle.launcher.GradleMain", "--console=plain", "--no-daemon", *tasks], env)
    dest = ROOT / "dist/deffector-debug.apk"
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(ROOT / "app/build/outputs/apk/debug/app-debug.apk", dest)
    print(f"APK: {dest}", flush=True)
    if args.install:
        adb = [sdk / "platform-tools/adb.exe"]
        if args.serial:
            adb += ["-s", args.serial]
        run([*adb, "install", "-r", dest], env)


if __name__ == "__main__":
    main()
