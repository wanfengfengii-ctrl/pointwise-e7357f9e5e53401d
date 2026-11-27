# 河湾社区广播剧节试听发行服务

早班编辑从演员提交的录音中编排试听片，按固定节目单核对私有校样。午班联络人办理同意与撤回，发行值班员公开节目。听众取得实际采用的试听片和署名，晚班凭原号和公开地址核对结果。

## 运行

需要 Python 3.11 和标准库。回归、事故核对和演示分别在临时目录启动两个本地 HTTP 服务，重开时复用该场景的数据库。

```sh
python3 -B check_project.py
python3 -B -m samples.incident
python3 -B -m samples.demo
```

日常运行在两个终端分别启动，使用项目内的两个不同数据库路径。首次启动建表，重复启动保留投稿、节目单、授权动作、校样和发行结果。启动不导入样例。

```sh
python3 -B -m editorial.http_api --db editorial.sqlite3 --port 8101 --peer http://127.0.0.1:8102 --desk-key local-festival
python3 -B -m release.http_api --db release.sqlite3 --port 8102 --peer http://127.0.0.1:8101 --desk-key local-festival
```

两端只监听 `127.0.0.1`，内部交接限同一工作台。除公开收听和发行站的 `GET /health` 就绪查询外，请求带 `Authorization: Bearer <desk-key>`。POST 使用 JSON 对象，请求体上限为 16 MiB。音频用标准 Base64 字符串 `audio_b64`。未知资源返回 404，参数或业务校验失败返回 422，原号冲突返回 409。错误体含 `error`，部分错误带附加字段。

`.pointwise-runtime.json` 登记两站联启、就绪路径、完整回归与事故核对及班次演示。联启使用本轮临时库，输出两个服务地址，工作台密钥为 `festival-sample`。

## 编辑台

| 请求 | 输入和结果 |
| --- | --- |
| `POST /recordings` | `actor_id`、`credit`、`audio_b64`。201 返回 `recording_id`、署名和测得的音频元数据。 |
| `GET /recordings/{id}` | 取回原件和元数据，供工作台核对及发行站预存。 |
| `POST /drafts` | `title` 和 `candidates`。每位候选含 `recording_id`、`start_ms`、`end_ms`。含 `draft_id` 时修正指定草稿。返回 `draft_id`。 |
| `GET /drafts/{id}` | 读回当前草稿。 |
| `POST /programs/freeze` | `draft_id`。201 返回 `program_id` 和固定校样清单。任何候选不合格时整次冻结失败，草稿可继续更正。 |
| `GET /programs/{id}` | 读回固定单和原时轴出处。优先位 `priority` 从 1 起，按输入顺序。 |
| `POST /consent` | `action_id`、`kind`、`actor_id`、`recording_id`、`purpose`。用途为 `preview_release`。`kind` 为 `grant` 或 `withdraw`。同意单编号即同意动作号。撤回另带 `grant_id`，须与演员、原提交和用途匹配。200 为 `applied`，202 为 `pending`。 |
| `GET /consent/{action_id}` | 读回编辑台已确认的动作状态。待办可按原参数重投 POST，原号与参数必须吻合。 |

每次投稿生成独立原件。支持非压缩 16 位单声道或双声道 PCM WAV。空音频、截断帧、不可用格式、没有整毫秒可用时长的音频及空署名均拒绝。时长为 `floor(1000 * 完整帧数 / 采样率)` 毫秒。有效片段满足 `0 <= start_ms < end_ms <= duration_ms`，端点须为整数。两个帧端点均按 `ceil(毫秒 * 采样率 / 1000)` 计算，终点帧排除。投影为空也拒绝。校样保留原时轴，音频保留原采样率、位宽、声道顺序及样值。保存草稿和冻结为独立动作。后续更正草稿可以冻结出新编号，旧固定单仍可读。

## 发行站

| 请求 | 输入和结果 |
| --- | --- |
| `POST /stages` | `program_id`。200 返回按优先位排列的已核验私有件清单。存在失败件时返回 422 `stage_failed` 及 `priorities`，失败件不可读，可重新预存。 |
| `GET /proofs/{program_id}/{priority}` | 读取一位候选的核验出处、摘要及 `audio_b64`。未预存或当前件不可用返回 404。 |
| `POST /releases` | `request_id` 和 `program_id`。成功返回固定首执。当前没有可用来源返回 422 `no_eligible_source`，保留原号及节目单绑定。 |
| `GET /releases/{request_id}` | 成立时返回首执，否则返回 `pending` 或 `no_eligible_source`。未知原号返回 404。 |
| `GET /listen/preview-{program_id}` | 公开返回首执字段及 `audio_b64`。首次公开前返回 404。 |

预存件按固定单和优先位绑定原提交、原区间和实际片段摘要。发行按固定顺序选择同时具备可读核验件和有效同意的第一位。一个来源有多份有效同意时采用最近正式成立的一份。编辑台确认的正式撤回与发行站的首次公开须有一致的先后。未确认的撤回可待办并按原号重投。已成立的公开音频、署名、原提交、同意单和首执保持固定。失答时用原号查单或同参重投。异参返回 `request_conflict`，即使两份单的候选完全相同。每份固定单对应一个公开地址，已公开后以另一原号发行同一固定单返回 `program_already_published`。

## 可重跑班次

`samples/shift.json` 给出两位演员、两个固定单和试听区间。两人提交同字节录音，各自保留原号与署名。8 kHz 样例的 `[100,300)` 毫秒对应 `[800,2400)` 帧，共 1600 帧。演示先预存并核对公开地址尚不可读，再让甲版首次公开并丢弃发行回包。撤回甲后，另一份尚未发行的固定单采用乙版。重开后晚班按第一份原号领回甲版，与听众实际取得的出处核对。回归另以 44.1 kHz 双声道样例、损坏片段、正式撤回与公开交错、原号冲突及重复初始化核对服务行为。

事故核对分别验证确认撤回后首次公开，以及发行失答后撤回再复领。可用 `python3 -B -m samples.incident Incident.test_withdrawal_first` 或 `python3 -B -m samples.incident Incident.test_publication_first` 单独执行。
