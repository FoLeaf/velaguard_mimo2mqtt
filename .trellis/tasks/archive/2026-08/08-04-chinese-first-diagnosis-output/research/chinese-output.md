# 中文优先诊断输出研究

## 现状

诊断请求的最终 system prompt 由 prompt_builder.py 将 skill 文本与固定 schema 指令拼接生成。当前 schema 指令要求 JSON-only 和字段结构，但没有语言要求，因此 MiMo 可以合法返回英文解释性文本。skill 文件和内置 fallback skill 也没有中文约束。

固定非模型结果同样含英文：fallback.py 返回 Cloud AI diagnosis is temporarily unavailable 等文本，providers/stub.py 返回 stub: no live MiMo call 和 Retry with PROVIDER=mimo for live diagnosis。

## 约束

- v2 结果 schema 只规定字段类型和风险枚举，不规定语言，不能新增翻译后处理来改写任意模型文本。
- JSON 字段名、topic、envelope、risk_level、source、错误码和协议状态必须保持不变。
- 技术名词、型号、单位、设备 ID、规则表达式和代码可保留英文或原样。
- skill 可能从文件加载，也可能因文件缺失使用内置默认文本，两条路径必须携带同一语言约束。

## 推荐实现

1. 在固定的 schema prompt 指令中加入中文优先规则，保证自定义 skill 也受约束。
2. 在内置 DEFAULT_DIAGNOSIS_SKILL 和 industrial_fault_diagnosis.md 中同步写入中文优先说明，方便单独阅读 skill 时语义完整。
3. 将 fallback 和 StubProvider 的面向用户固定文本改为中文，保留协议元数据。
4. 用 prompt 测试检查语言约束及技术字段保留说明，用 fallback/stub 测试检查中文固定文案和来源字段。

## 不采用的方案

不在 schema validator 中检测中文比例，也不对模型返回做机器翻译。语言检测和自动翻译会增加误判、破坏技术词和改变模型原始诊断事实的风险。
