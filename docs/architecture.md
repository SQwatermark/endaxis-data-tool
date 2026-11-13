# 数据读取与发布

## 职责边界

工具输出 Endaxis 编译器需要的原生配置来源，不生成战斗运行时定义。

| 层 | 模块 | 职责 |
| --- | --- | --- |
| 资源准备 | `prepare`、`manifest`、`key_host` | 通过 AKE 读取 BLC/CHK，按 manifest 选择补充资源包；隔离原生密钥调用 |
| 二进制读取 | `unity.binary` | 显式字节序、有界视图、对齐与错误位置 |
| 资源包 | `unity.bundle`、`compression`、`endfield_transform` | 包头、目录、数据块、解码和长度校验 |
| 序列化文件 | `unity.serialized_file` | 类型表、对象表、外部文件身份及 RefTypes |
| 类型树 | `unity.typetree` | 通用读取、字段范围、managed reference 和带类型的文本输出 |
| 文档投影 | `decoders` | 将明确的原生字段组织为编译器来源文档；不决定游戏执行语义 |
| 提取与发布 | `extract`、`export`、`documents` | 资源身份、摘要、清单验证及原子发布 |
| 服务 | `server` | 只读提供 AKE 输出与补充快照 |

## 身份与引用

对象身份由 SerializedFile 身份和整数 PathID 共同确定。PPtr 的 file ID 为零时查询当前文件，正数按外部引用表定位文件。找不到的外部文件不伪造对象；被选择的配置必须能唯一定位。container 的主对象必须与 preload 中唯一的 MonoBehaviour 相同。

Managed reference 的 RID 只在所属对象内有效。类型、命名空间和程序集共同定位 RefTypes。载荷按对应类型树读取；RefTypes 描述中的宿主 registry 不在每个引用载荷内再次读取。引用边界取自读取位置，不扫描看似匹配的字节序列。

## 数据表达

读取层保留原生字段名、顺序及精确整数。对象描述和引用列表中的 PathID、RID 以十进制字符串表达，避免 JavaScript 精度损失。布尔值依 TypeTree 的布尔标记转换，不能把所有 UInt8 都视为布尔值。Float32 读取保留实际数值；文本及 JSON 投影采用可还原相同 Float32 的十进制表示。

角色来源文档提供根模板、能力系统及连携条件引用。能力实体来源文档提供生命周期、技能登记、黑板和组件配置。投射物仅提供回调技能身份、命中筛选和黑板，不发布运动模拟参数。敌人保留原始对象字节，供编译器现有解析器消费。

## 完整性与发布

资源包及 SerializedFile 版本必须显式支持。所有长度、计数、对象范围、引用身份及解码边界都进行检查；缺少类型树和未知格式会失败，不以旧布局猜测或部分结果替代。

`prepare` 保存版本、包摘要和请求的 container。`extract` 在读取前检查包清单，在发布前核对请求资源全部存在。`export` 再验证对象文档摘要，将补充集合和 `snapshot.json` 一起发布。提取和发布都先写临时目录，成功后重命名到不存在的目标，失败时不留下可被服务读取的半成品快照。

TableCfg、JsonData 和图片由 AKE 提供。来源服务不重写这些数据，也不把不同版本输入自动合并；调用者负责提供同版本资源。
