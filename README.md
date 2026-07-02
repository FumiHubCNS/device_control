# device-control

HV電源やオシロスコープなど、ttyUSB/SCPI/VISA/Ethernetで操作する実験機器の統合ライブラリです。

## Layout

- `src/device_control/protocol`: シリアル、SCPI、IEEE 488.2 blockなどの共通通信ヘルパ
- `src/device_control/webui`: WebUI共通テンプレート
- `src/device_control/kikusui`: KIKUSUI KX-S系HV電源のttyUSB制御とWebUI
- `src/device_control/mho98`: RIGOL/MHO98系オシロスコープのMinimum triggered DAQ、HDF5保存、CLI、WebUI
- `src/device_control/tektronix/afg1062`: Tektronix AFG1062 Function GeneratorのCLI/WebUI
- `src/device_control/tektronix/mdo3034`: Tektronix MDO3034オシロスコープの設定確認、WebUI波形取得、CSV保存

## Commands

USB接続機器の確認:

```bash
uv run device-control-list-usb
uv run device-control-list-usb --json
```

`/dev/usbtmc0` で `Permission denied` になる場合は、USB-TMCデバイスへの読み書き権限を付けます。
例:

```bash
sudo usermod -aG plugdev "$USER"
echo 'SUBSYSTEM=="usbmisc", KERNEL=="usbtmc*", MODE="0660", GROUP="plugdev"' | \
  sudo tee /etc/udev/rules.d/60-usbtmc.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

その後、USBケーブルを挿し直すか再ログインしてから確認します。

USB-TMCで応答確認だけ行う場合:

```bash
uv run device-control-scpi-query --usbtmc /dev/usbtmc0 '*IDN?'
uv run device-control-scpi-query --usbtmc /dev/usbtmc0 --write-termination '\r\n' '*IDN?'
```

KIKUSUI HV WebUI:

```bash
uv run device-control-kikusui-web --host 0.0.0.0 --port 8081
```

オシロスコープの従来CLI相当:

```bash
uv run device-control-scope-daq -ip 172.16.206.60 -n 10 -of scope_data.h5 -ch 1 2 3 4
```

オシロスコープWebUI:

```bash
uv run device-control-scope-web --ip 172.16.206.60 --host 0.0.0.0 --port 8082
```

USB権限付与

```bash
sudo chmod a+rw /dev/usbtmc0
```

Tektronix AFG1062の現状確認:

```bash
uv run device-control-afg1062 --resource 'USB0::0x0699::...::INSTR' status
# Linux USB-TMCを直接使う場合(VISAなし)
uv run device-control-afg1062 --usbtmc /dev/usbtmc0 status

# 応答なしSCPIコマンドを直接送って、その後に状態を問い合わせる
uv run device-control-scpi-query --usbtmc /dev/usbtmc0 --write-only 'OUTPut1:STATe OFF'
uv run device-control-scpi-query --usbtmc /dev/usbtmc0 'OUTPut1:STATe?'

uv run device-control-scpi-query --usbtmc /dev/usbtmc0 --write-only 'SOURce1:FREQuency:FIXed 1000Hz'
uv run device-control-scpi-query --usbtmc /dev/usbtmc0 'SOURce1:FREQuency:FIXed?'
```

Tektronix AFG1062のチャンネル設定:

```bash
uv run device-control-afg1062 --resource 'USB0::0x0699::...::INSTR' set -ch 1 \
  --waveform SIN --frequency 1000 --amplitude 1.0 --offset 0 --output on
```

Tektronix AFG1062 WebUI:

```bash
uv run device-control-afg1062-web --resource 'USB0::0x0699::...::INSTR' --host 0.0.0.0 --port 8083
# Linux USB-TMCを直接使う場合(VISAなし)
uv run device-control-afg1062-web --usbtmc /dev/usbtmc0 --host 0.0.0.0 --port 8083
# WebUIが実際に送るSCPIをサーバー側ターミナルへ表示する
uv run device-control-afg1062-web --usbtmc /dev/usbtmc0 --host 0.0.0.0 --port 8083 --verbose
```

Tektronix MDO3034 WebUI:

```bash
uv run device-control-mdo3034-web --ip 172.16.206.60 --host 0.0.0.0 --port 8084
```

MDO3034の波形取得確認:

```bash
uv run device-control-mdo3034 --ip 172.16.206.60 --verbose acquire -ch '1' --stop 2000
uv run device-control-mdo3034 --ip 172.16.206.60 --verbose acquire -ch '1' --trigger-window --pretrigger-points 1000 --posttrigger-points 1000
uv run device-control-mdo3034 --ip 172.16.206.60 --verbose acquire -ch '1' --single --timeout 60
```

MDO3034をsocket server経由で使う場合は、WebUIのSocketチェックをONにするか、VISA resourceに
`TCPIP0::<ip>::4000::SOCKET` を指定します。

PyQtGraphのライブビュアーも使う場合:

```bash
uv sync --extra viewer
```
