# Endaxis Data Tool

导出 Endaxis 游戏数据编译器需要的补充原生数据，并提供本地只读来源服务。

TableCfg、JsonData 和图片使用 AKE Data Tool 的导出结果。补充导出覆盖角色模板、能力实体模板、投射物战斗配置、敌人模板、GlobalBuff、GameplayTagConfigSet 及技能设置等原生配置。投射物运动参数不进入补充导出。

## 依赖与安装

需要 Python 3.11+。准备 VFS 资源时需要包含 `ake_tool.json_host.vfs` 的 AKE Data Tool 源码目录。原生密钥宿主需要 Windows x64 和匹配版本的完整游戏运行时；已有 VFS 密钥文件时无需启动原生宿主。对象提取、快照发布和服务均在 Python 内执行。

```powershell
python -m pip install -e .
```

`unity` 读取终末地定制包和 UnityFS、SerializedFile、对象引用及 TypeTree；`decoders` 将原生字段投影为编译器来源文档。工具不加载 VFS 浏览器，也不维护第二套 AKE JsonData 解码器。

## 导出流程

先用 AKE Data Tool 准备同版本的 VFS，并导出 TableCfg、Json 与图片。以下输入路径均由调用者指定，输出路径必须尚不存在。

### 1. 选择并提取补充资源包

```powershell
endaxis-data-tool prepare --ake-tool-root <ake-data-tool目录> --vfs-root <AKE工作目录> --runtime-root <完整运行时目录> --version <来源版本> --output <bundle输出目录>
```

`--runtime-root` 可以换成 `--key-file <密钥文件>`。密钥文件支持 32 字节二进制或 Base64，密钥不会写入输出清单或日志。原生密钥查询在独立子进程中运行，结束后整个宿主进程退出。

此步骤复用 AKE 的 BLC/CHK 读取器，按 manifest.hgmmap 选择数据资源包，保留 Bundle 对 InitialBundle 的覆盖优先级。只导出匹配的资源包，并校验读取内容。`bundles.json` 保存来源版本、manifest 摘要、资源路径及包摘要。

### 2. 提取 Unity 对象

```powershell
endaxis-data-tool extract --input <bundle输出目录> --output <对象输出目录> --version <来源版本>
```

使用准备阶段的输出时，会校验 `bundles.json` 中的版本、包摘要和预期资源是否全部导出。也可以使用已经去除外层 VFS 加密的资源包目录，文件后缀为 `.ab`。读取器识别其中的终末地定制格式或标准 UnityFS。配置按精确 container 和 preload 定位；重名身份或对象不唯一时中止。

对象必须具有完整 TypeTree，managed reference 的载荷按宿主 SerializedFile 的 RefTypes 读取，不能通过扫描字节猜测类型或边界。缺失类型树、未知布局或未完整消费对象数据时失败。输出是带来源信息的 JSON 对象文档，`raw-manifest.json` 保存其版本、身份、container 和摘要。

### 3. 发布补充快照

```powershell
endaxis-data-tool export --manifest <对象输出目录>/raw-manifest.json --output <补充快照目录>
```

发布前校验每份对象文档的 SHA-256，整批成功后发布。读取完整性由 `decodeStatus` 表示；它不代表编译器已实现该配置的全部行为。敌人模板保留原始对象，品阶解析由编译器完成。

### 4. 启动来源服务

```powershell
endaxis-data-tool serve --json-root <AKE的Json目录> --table-root <AKE的TableCfg目录> --image-root <AKE的images目录> --supplemental-root <补充快照目录> --version <来源版本>
```

监听 `127.0.0.1:8766`。`--image-root` 可省略；省略时不提供图片补缺。所有根目录均为只读。

| 路径 | 内容 |
| --- | --- |
| `/api/data/TableCfg-current/<name>.json` | AKE 表格导出 |
| `/api/data/<collection>/<file>.json` | AKE Json 或补充快照中的资源 |
| `/api/data/<collection>/manifest.json` | 集合文件清单 |
| `/api/images/manifest.json` | AKE 本地导出图片的原始路径清单 |
| `/api/images/<path>` | AKE 本地图片文件 |

响应包含 `X-Endaxis-Source`、`X-Endaxis-Provider` 和 `X-Endaxis-Version`。AKE 与补充数据的来源身份分别为 `ake-data-tool` 和 `endaxis-data-tool`。服务检查补充快照的版本；调用者还应保证选择的 AKE 目录来自同一版本，目录参数自身不能证明版本一致。

## 补充集合

- `CharacterData`、`AbilityEntityData`、`ProjectileData` 提供编译器需要的模板、技能注册和黑板。
- `EnemyData` 提供敌人模板原始数据及精确 container。
- `GlobalBuffData` 提供 GlobalBuff TypeTree。
- `GameplayTagData` 保留配置集及其成员的 TypeTree、CAB、PathID 和外部依赖，供编译器检查引用闭包。
- `NativeConfig` 提供 skillsetting、timedilationconfig、hitstopconfig、battlecommandmappingconfig、gameplaymiscsetting、movementsetting_default。

## 开发与验证

```powershell
python -m unittest discover -s tests
```

结构和读取边界见 [架构说明](docs/architecture.md)。合成测试覆盖包提取、TypeTree、managed reference、原始整数身份、布尔字段及错误时不发布。真实资源验证需要另外检查完整包清单、原始对象摘要、导出字段和编译器消费结果。游戏资源、运行时、密钥、导出快照与诊断日志不提交到源码仓库。
