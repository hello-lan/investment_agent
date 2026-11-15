@echo off
setlocal EnableDelayedExpansion

REM ============================================================
REM Investment Agent 启动脚本 (Windows)
REM 用法: start.bat [--reload] [--port PORT]
REM ============================================================

cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "RELOAD_FLAG="
set "PORT=8000"
if defined APP_PORT set "PORT=%APP_PORT%"

REM 解析参数
:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--reload" (
    set "RELOAD_FLAG=--reload"
    shift
    goto parse_args
)
if /i "%~1"=="--port" (
    if "%~2"=="" (
        echo 错误: --port 需要指定端口号
        exit /b 1
    )
    set "PORT=%~2"
    shift
    shift
    goto parse_args
)
if /i "%~1"=="--help" goto show_help
if /i "%~1"=="-h" goto show_help
echo 未知参数: %~1
echo 用法: start.bat [--reload] [--port PORT]
exit /b 1

:show_help
echo 用法: start.bat [--reload] [--port PORT]
echo.
echo 选项:
echo   --reload      启用 uvicorn 热重载（开发模式）
echo   --port PORT   指定监听端口（默认 8000）
echo   --help, -h    显示帮助信息
exit /b 0

:args_done

REM ----------------------------------------------------------
REM Step 1: 创建/激活虚拟环境
REM ----------------------------------------------------------
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [1/3] 创建虚拟环境...
    where python >nul 2>&1
    if errorlevel 1 (
        echo 错误: 未找到 python，请先安装 Python 3 并加入 PATH
        exit /b 1
    )
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo 错误: 创建虚拟环境失败
        exit /b 1
    )
)

echo [1/3] 激活虚拟环境...
call "%VENV_DIR%\Scripts\activate.bat"

REM ----------------------------------------------------------
REM Step 2: 安装依赖
REM ----------------------------------------------------------
echo [2/3] 安装依赖...
REM pip install -r requirements.txt

REM ----------------------------------------------------------
REM Step 3: 启动服务
REM ----------------------------------------------------------
if defined RELOAD_FLAG (
    echo [3/3] 启动服务（开发模式，热重载已启用^） -^> http://127.0.0.1:!PORT!
) else (
    echo [3/3] 启动服务 -^> http://127.0.0.1:!PORT!
)

uvicorn investment_agent:app --host 0.0.0.0 --port !PORT! %RELOAD_FLAG%
