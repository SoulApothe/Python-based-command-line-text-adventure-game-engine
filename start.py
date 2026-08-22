import json
import os
import sys
import time
import operator
import re
from datetime import datetime
from pathlib import Path

# 尝试导入 msvcrt（Windows 专用，用于非阻塞按键检测）
try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# 设置标准输出为 UTF-8，避免 Windows 控制台中文乱码或报错
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

class GalgameEngine:
    # ==================== 可调整参数区域 ====================
    # 历史回忆条数：读档后显示的最近对话条数
    RECALL_SIZE = 20
    
    # 手动存档槽位数（不包含自动存档槽位0）
    SAVE_SLOT_COUNT = 9
    
    # 打字机速度：每个字符的显示间隔（秒），越小越快
    TYPE_SPEED = 0.03
    
    # 自动播放间隔：两句话之间的等待时间（秒），可调整
    AUTO_PLAY_INTERVAL = 1.0
    # ========================================================

    def __init__(self, content_path="game.json"):
        self.base_dir = Path(__file__).parent
        # 游戏内容目录（game 文件夹）
        self.game_dir = self.base_dir / "game"
        self.game_dir.mkdir(exist_ok=True)
        
        self.content_path = self.game_dir / content_path
        self.save_dir = self.game_dir / "saves"
        self.save_dir.mkdir(exist_ok=True)

        self.content = self.load_content()
        self.meta = self.content.get("meta", {})
        self.characters = self.content.get("characters", {})
        self.global_flags = self.content.get("global_flags", {})
        self.scenes = self.content.get("scenes", {})

        self.current_scene = "start"
        self.runtime_characters = {}
        self.init_characters()

        # 玩家自定义变量（由输入标记动态填充）
        self.player_vars = {}

        # 对话历史记录
        self.history = []

        # 自动播放开关
        self.auto_play = False

        # 打字机速度（引用类变量，方便修改）
        self.type_speed = self.TYPE_SPEED
        
        # 当前场景起始历史索引（用于读档时截断历史）
        self.current_scene_start_index = 0

    def load_content(self):
        """加载 game.json，若文件不存在则创建示例并引导玩家"""
        try:
            with open(self.content_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            # 文件不存在，在脚本同目录生成提示文件
            self.create_prompt_file()
            # 生成示例 JSON 文件
            self.create_default_content()
            self.ask_for_format_guide()
            input("按回车键退出...")
            sys.exit(0)
        except json.JSONDecodeError as e:
            print(f"错误：JSON 解析失败 - {e}")
            sys.exit(1)

    def create_prompt_file(self):
        """在脚本同目录生成 system prompt.txt 提示文件"""
        prompt_file = self.base_dir / "system prompt.txt"
        # 提示文本内容（使用原始字符串避免转义）
        prompt_text = r"""你是一位专业的视觉小说（Galgame）剧本改编与 JSON 生成专家。你的任务是将用户提供的小说原著内容，拆解、改写并输出为符合指定引擎要求的 `game.json` 文件。该文件将被直接用于游戏引擎运行，因此必须严格遵循下述格式规范，且确保 JSON 结构完整、可解析、可运行。

## 初始引导
如果用户没有提供任何小说内容，请先简单说明你的能力：“我可以将小说改编为 Galgame 用的 JSON 文件，请提供小说原文或具体章节。” 然后等待用户输入。不要自行编造内容。

## 第一步：内容拆分与改写

1. 通读小说原文，识别主要人物、场景、对话、关键事件和结局。
2. 将小说内容改写为适合 Galgame 表演的文本形式：
   - **旁白**：用第三人称叙述环境、动作、心理等，保持简洁，每段旁白可独立成段。
   - **人物对话**：格式为“角色名 + 空格 + 说的话”，例如：`星见 早上好。`
   - 对话与旁白应交替出现，形成清晰的叙事节奏。
3. 根据剧情需要，将故事拆分为多个**场景**（Scene）。每个场景内可以包含多段文本（按换行符分隔，引擎会逐段暂停等待玩家按回车）。
4. **尊重原著**：尽量保留原文的完整情节、对话和关键描写，不要为了强行添加分支而删减内容。如果原文有较多细节，可以拆分成更多场景，但不要遗漏重要事件。
5. **分支与输入判断**：
   - 只有当原文中存在明确的分支选择、好感度计算、影响剧情走向的决策点，或需要玩家自定义输入（如起名）时，才添加对应的选项（Options）、条件（Conditions）、效果（Effects）和输入标记（`{input:...}`）。
   - 如果原文是**纯线性叙事**，没有任何分支或玩家可影响结局的机制，则不要强行添加选项或输入，只生成纯对话场景链（每个场景通过 `next_scene` 连接）。
   - 如果原文有多个结局或隐藏路线，将这些分支体现在选项和条件中。
   - 如果原文没有角色属性变化（如好感度），则角色定义中可以不包含 `attributes`，或只保留空的 `attributes` 对象。
   - 如果原文没有需要玩家输入的内容，则完全不使用输入标记，也不要生成 `player_inputs` 相关结构（引擎已不依赖该顶层字段，输入点由文本内标记触发）。

## 第二步：JSON 结构规范

生成的 JSON 文件必须严格包含以下顶层字段：

```json
{
  "meta": { ... },
  "characters": { ... },
  "global_flags": { ... },
  "scenes": { ... }
}
```

### 1. `meta`（元信息，可选）
可以包含标题、版本等，例如：
```json
"meta": {
  "title": "示例游戏",
  "version": "1.0"
}
```

### 2. `characters`（角色定义，必需）
对象，键为角色ID（字符串），值为角色定义对象。
每个角色定义格式：
```json
"角色ID": {
  "display_name": "显示名称（可选）",
  "attributes": {
    "属性名": 初始数值
  },
  "flags": {
    "标志名": 初始布尔值
  }
}
```
- `attributes` 可自定义任意属性（如“好感度”），初始值为数字。**如果原文没有属性变化，可以省略 `attributes` 或保留为空对象。**
- `flags` 用于存储角色私有状态（如“是否已见面”），可按需设置。

示例：
```json
"characters": {
  "星见": {
    "display_name": "七瀬 星见",
    "attributes": { "好感度": 0 },
    "flags": { "已见面": false }
  },
  "琉璃": {
    "display_name": "神代 琉璃",
    "attributes": { "好感度": 0 },
    "flags": {}
  }
}
```

### 3. `global_flags`（全局标志，可选）
对象，键为标志名，值为初始值（数字、字符串、布尔均可）。**如果原文没有跨场景的状态变量，可以省略或留空 `{}`。**
示例：
```json
"global_flags": {
  "周目数": 1,
  "是否完成隐藏剧情": false
}
```

### 4. `scenes`（场景集合，必需）
对象，键为场景ID（字符串），值为场景对象。必须包含 `"start"` 场景作为游戏开始点，建议包含 `"end"` 场景作为通用结束点（也可用自定义结束场景）。

场景分为两种类型：

#### A. 纯对话场景
格式：
```json
"场景ID": {
  "text": "对话或旁白文本...",
  "next_scene": "下一个场景ID"
}
```
- `text` 支持使用 `\n` 分隔多段，每段会单独显示并等待玩家按回车。
- `next_scene` 指定玩家按回车后跳转的场景ID，若未定义则跳转到 `"end"`。

#### B. 选项场景（仅在原文有分支时使用）
格式：
```json
"场景ID": {
  "text": "文本...",
  "options": [
    {
      "text": "选项显示文字",
      "next_scene": "跳转场景ID",
      "conditions": [ ... ],  // 可选，条件数组
      "effects": [ ... ]      // 可选，效果数组
    },
    ...
  ]
}
```
- `options` 数组中的每个选项可包含：
  - `text`：选项文字（支持变量替换）。
  - `next_scene`：选择后跳转的场景ID。
  - `conditions`：条件数组，所有条件都满足时该选项才显示。
  - `effects`：效果数组，选择后按顺序执行。
- **如果没有分支，则不要添加 `options` 字段，只保留 `text` 和 `next_scene`。**

### 5. 条件系统（conditions）
每个条件对象必须包含 `type` 字段，支持以下类型：

#### (1) 属性条件
```json
{
  "type": "attribute",
  "target": "角色ID",
  "attribute": "属性名",
  "operator": "比较运算符",
  "value": 数值
}
```
运算符支持：`">"`, `">="`, `"<"`, `"<="`, `"=="`, `"!="`。
示例：
```json
{ "type": "attribute", "target": "星见", "attribute": "好感度", "operator": ">=", "value": 10 }
```

#### (2) 全局标志条件
```json
{
  "type": "global_flag",
  "key": "标志名",
  "operator": "比较运算符（可选，默认 ==）",
  "value": 期望值
}
```
示例：
```json
{ "type": "global_flag", "key": "周目数", "operator": "==", "value": 2 }
```

#### (3) 角色标志条件
```json
{
  "type": "flag",
  "target": "角色ID（可选，不填则检查全局标志）",
  "key": "标志名",
  "value": 期望值
}
```
示例：
```json
{ "type": "flag", "target": "星见", "key": "已见面", "value": true }
```

### 6. 效果系统（effects）
效果对象也必须有 `type` 字段，支持以下类型：

#### (1) 增加属性值
```json
{ "type": "add_attribute", "target": "角色ID", "attribute": "属性名", "value": 增减数值（可为负） }
```

#### (2) 设置属性值
```json
{ "type": "set_attribute", "target": "角色ID", "attribute": "属性名", "value": 新值 }
```

#### (3) 设置全局标志
```json
{ "type": "set_global_flag", "key": "标志名", "value": 新值 }
```

#### (4) 设置角色标志
```json
{ "type": "set_flag", "target": "角色ID（可选）", "key": "标志名", "value": 新值 }
```
若不指定 `target`，则效果等同于 `set_global_flag`。

#### (5) 增加全局标志数值
```json
{ "type": "add_global_flag", "key": "标志名", "value": 增减数值 }
```

### 7. 玩家自定义输入与变量替换
- 仅当原文需要玩家输入（如起名）时才使用。在任意文本中插入 `{input:变量名:提示文字}` 可让玩家输入内容，例如：
  ```
  "text": "你叫{input:player_name:请输入你的名字}，今年16岁。"
  ```
  引擎会在该处暂停并提示输入，输入值存入 `player_vars`，之后文本中所有 `{变量名}` 会被替换为输入值。
- 若变量已存在（如读档后），则不再要求输入。
- 提示文字可省略，默认显示 `请输入 变量名：`。
- 也可在文本中直接用 `{变量名}` 引用（需确保已通过输入标记定义过）。
- **如果原文不需要玩家输入，则完全不使用此功能，不要插入任何 `{input:...}` 标记。**

### 8. 换行与文本格式
- 场景文本中可使用 `\n` 分隔多个段落，每个段落显示后会等待玩家按回车。
- 人物对话建议单独成行，格式如 `角色名 对话内容`，旁白单独成行。
- 文本中不要使用多余的空格或特殊标记，保持简洁。

## 第三步：生成可直接运行的 JSON 文件

根据以上规范，生成一个完整的 `game.json` 文件，必须满足：
- 包含 `meta`、`characters`、`global_flags`、`scenes` 四个字段。
- `scenes` 中有 `"start"` 场景和至少一个结束场景（建议 `"end"`）。
- 如果原文有分支或属性变化，则应包含对应的选项、条件和效果；否则可以全部是纯对话场景。
- 如果原文有需要玩家输入的内容，则使用输入标记；否则不使用。
- 尊重原著，不随意删减情节，保持故事的完整性。
- 确保 JSON 语法正确，无尾逗号，所有字符串使用双引号。

## 第四步：输出要求

请直接输出生成的 JSON 文件内容，不要包含任何额外解释、注释或代码块标记（除非用户要求）。输出的内容应以 `{` 开头，以 `}` 结尾，并保证缩进美观。

---

## 附录：完整示例 JSON（供参考格式）

```json
{
  "meta": {
    "title": "星之邂逅",
    "version": "1.0"
  },
  "characters": {
    "星见": {
      "display_name": "七瀬 星见",
      "attributes": {
        "好感度": 0
      },
      "flags": {
        "已见面": false
      }
    },
    "琉璃": {
      "display_name": "神代 琉璃",
      "attributes": {
        "好感度": 0
      },
      "flags": {}
    }
  },
  "global_flags": {
    "周目数": 1
  },
  "scenes": {
    "start": {
      "text": "清晨，{input:player_name:请输入你的名字}从睡梦中醒来。\n新的一天开始了。",
      "next_scene": "encounter"
    },
    "encounter": {
      "text": "在上学路上，你遇到了一个女孩。她有着如星空般璀璨的眼眸。",
      "options": [
        {
          "text": "主动打招呼",
          "next_scene": "greet",
          "effects": [
            { "type": "add_attribute", "target": "星见", "attribute": "好感度", "value": 2 },
            { "type": "set_flag", "target": "星见", "key": "已见面", "value": true }
          ]
        },
        {
          "text": "默默走过",
          "next_scene": "end_bad",
          "effects": []
        }
      ]
    },
    "greet": {
      "text": "“早上好。”你微笑着说道。\n星见似乎有些惊讶，随后也露出笑容：“早上好，我叫星见。”",
      "next_scene": "talk_choice"
    },
    "talk_choice": {
      "text": "你们边走边聊。星见似乎对星座很感兴趣。",
      "options": [
        {
          "text": "“你也喜欢星星吗？”",
          "next_scene": "share_star",
          "conditions": [
            { "type": "attribute", "target": "星见", "attribute": "好感度", "operator": ">=", "value": 2 }
          ],
          "effects": [
            { "type": "add_attribute", "target": "星见", "attribute": "好感度", "value": 3 }
          ]
        },
        {
          "text": "“今天天气不错。”",
          "next_scene": "weather",
          "effects": [
            { "type": "add_attribute", "target": "星见", "attribute": "好感度", "value": 1 }
          ]
        },
        {
          "text": "（沉默不语）",
          "next_scene": "silent",
          "conditions": [
            { "type": "attribute", "target": "星见", "attribute": "好感度", "operator": "<=", "value": 5 }
          ],
          "effects": [
            { "type": "add_attribute", "target": "星见", "attribute": "好感度", "value": -1 }
          ]
        }
      ]
    },
    "share_star": {
      "text": "星见的眼睛亮了起来：“你也喜欢星星吗？太好了！我知道一个绝佳的观星地点。”",
      "next_scene": "invite"
    },
    "weather": {
      "text": "星见礼貌地笑了笑：“是啊，不过晚上云可能会多，看不到星星呢。”",
      "next_scene": "invite_low"
    },
    "silent": {
      "text": "气氛变得有些尴尬。星见也不再说话，只是低头走路。",
      "next_scene": "end_bad"
    },
    "invite": {
      "text": "星见鼓起勇气：“那个……如果你愿意的话，今晚可以一起去观星吗？”",
      "options": [
        {
          "text": "欣然答应",
          "next_scene": "good_end",
          "conditions": [
            { "type": "attribute", "target": "星见", "attribute": "好感度", "operator": ">=", "value": 5 }
          ],
          "effects": []
        },
        {
          "text": "犹豫后拒绝",
          "next_scene": "end_normal",
          "effects": []
        }
      ]
    },
    "invite_low": {
      "text": "星见似乎有些犹豫，但还是开口：“那个……如果你不介意，今晚一起去天文馆？”",
      "options": [
        {
          "text": "答应",
          "next_scene": "normal_end",
          "effects": []
        },
        {
          "text": "拒绝",
          "next_scene": "end_bad",
          "effects": []
        }
      ]
    },
    "good_end": {
      "text": "夜晚，星空下，你们并肩而坐。星见指着天空：“看，那是天琴座。”\n你转头看向她，心中涌起暖意。\n（达成结局：星之约定）",
      "next_scene": "end"
    },
    "normal_end": {
      "text": "天文馆里，你们度过了一个愉快的夜晚。虽然星见偶尔会望着窗外的星空出神。\n（达成结局：普通朋友）",
      "next_scene": "end"
    },
    "end_bad": {
      "text": "你们最终没有更多交集，各自走向不同的方向。\n（达成结局：擦肩而过）",
      "next_scene": "end"
    },
    "end": {
      "text": "故事结束。感谢游玩！",
      "next_scene": "end"
    }
  }
}
```

现在，请根据用户提供的小说内容，按照以上规则进行拆分、改写，并输出最终的 `game.json` 文件。如果用户没有提供内容，请先提示用户输入小说。"""
        try:
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(prompt_text)
            print(f"已在 {prompt_file} 生成提示文件。")
        except Exception as e:
            print(f"生成提示文件失败：{e}")

    def create_default_content(self):
        """生成一个简单的示例 JSON 文件，引导玩家开始"""
        default_content = {
            "meta": {
                "title": "示例游戏",
                "version": "1.0"
            },
            "characters": {
                "角色": {
                    "display_name": "角色名",
                    "attributes": {"好感度": 0},
                    "flags": {}
                }
            },
            "global_flags": {"周目数": 1},
            "scenes": {
                "start": {
                    "text": "这是一个示例场景。\n请编辑 game.json 来开始你的故事。",
                    "next_scene": "end"
                },
                "end": {
                    "text": "游戏结束。",
                    "next_scene": "end"
                }
            }
        }
        try:
            with open(self.content_path, "w", encoding="utf-8") as f:
                json.dump(default_content, f, ensure_ascii=False, indent=2)
            print(f"未找到 {self.content_path}，已自动创建示例文件。")
        except Exception as e:
            print(f"创建示例文件失败：{e}")

    def ask_for_format_guide(self):
        """询问玩家是否想查看编写规则"""
        print("\n是否想自己编写游戏内容？")
        while True:
            choice = input("输入 y 查看编写规则，输入 n 退出：").strip().lower()
            if choice == 'y':
                self.show_format_guide()
                break
            elif choice == 'n':
                break
            else:
                print("请输入 y 或 n。")

    def show_format_guide(self):
        """打印简要的 JSON 编写规则"""
        guide = """
=== Galgame JSON 编写简要规则 ===
1. 整体结构：包含 "meta"、"characters"、"global_flags"、"scenes" 四个部分。
2. 角色定义：在 "characters" 中定义角色ID、显示名称、属性（如好感度）和私有标志。
3. 全局标志：在 "global_flags" 中定义跨场景变量。
4. 场景：在 "scenes" 中定义场景ID，每个场景包含 "text"（对话文本），可选 "options"（选项数组）。
   - 纯对话场景：只有 "text" 和 "next_scene"（按回车跳转）。
   - 选项场景：包含 "options"，每个选项有 "text"、"next_scene"、可选 "conditions"（条件）和 "effects"（效果）。
5. 条件类型：支持属性条件（attribute）、全局标志条件（global_flag）、角色标志条件（flag）。
6. 效果类型：支持增加属性（add_attribute）、设置属性（set_attribute）、设置标志（set_flag/set_global_flag）等。
7. 玩家输入：在文本中使用 {input:变量名:提示} 插入输入点，之后用 {变量名} 引用。
8. 换行：使用 \\n 分隔同一场景内的多段文本，每段会单独暂停。
9. 文本转换：本引擎提供一个AI系统提示词，支持将自然语言转换成可识别的json文件。
详细说明请参考完整文档。
"""
        print(guide)

    def init_characters(self):
        for char_id, char_def in self.characters.items():
            self.runtime_characters[char_id] = {
                "attributes": dict(char_def.get("attributes", {})),
                "flags": dict(char_def.get("flags", {}))
            }

    def replace_vars(self, text):
        """将文本中的 {变量名} 替换为玩家自定义值"""
        for key, value in self.player_vars.items():
            text = text.replace(f"{{{key}}}", str(value))
        for key, value in self.global_flags.items():
            if isinstance(value, str):
                text = text.replace(f"{{{key}}}", value)
        return text

    def type_text(self, text):
        """打字机效果显示文本，支持按回车直接显示剩余部分（不自动换行）"""
        text = self.replace_vars(text)
        if not text:
            return
        i = 0
        n = len(text)
        while i < n:
            if HAS_MSVCRT and msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\r', b'\n'):
                    print(text[i:], end='', flush=True)
                    return
            print(text[i], end='', flush=True)
            time.sleep(self.type_speed)
            i += 1
        # 不换行，由外层控制

    def display_text_with_inputs(self, text):
        """处理文本中的 {input:...} 标记，并返回替换后的完整文本"""
        pattern = re.compile(r'\{input:([^}:]+)(?::([^}]*))?\}')
        output_text = ""
        last_pos = 0
        for match in pattern.finditer(text):
            segment = text[last_pos:match.start()]
            processed_segment = self.replace_vars(segment)
            self.type_text(processed_segment)
            output_text += processed_segment
            # 输入前需要换行（如果光标不在行首）
            if processed_segment:
                print()  # 换行
            input_id = match.group(1)
            prompt = match.group(2) or f"请输入 {input_id}："
            if input_id in self.player_vars:
                value = self.player_vars[input_id]
                print(prompt + value)  # 直接显示已存在的值
            else:
                while True:
                    value = input(prompt).strip()
                    if value:
                        self.player_vars[input_id] = value
                        break
                    print("输入不能为空，请重新输入。")
            output_text += value
            last_pos = match.end()
        tail = text[last_pos:]
        processed_tail = self.replace_vars(tail)
        self.type_text(processed_tail)
        output_text += processed_tail
        return output_text

    @staticmethod
    def compare(a, op, b):
        ops = {
            ">": operator.gt,
            ">=": operator.ge,
            "<": operator.lt,
            "<=": operator.le,
            "==": operator.eq,
            "!=": operator.ne
        }
        if op not in ops:
            return False
        return ops[op](a, b)

    def check_condition(self, cond):
        cond_type = cond.get("type")
        if cond_type == "attribute":
            target = cond["target"]
            attr = cond["attribute"]
            op = cond["operator"]
            value = cond["value"]
            current = self.runtime_characters.get(target, {}).get("attributes", {}).get(attr)
            if current is None:
                return False
            return self.compare(current, op, value)
        elif cond_type == "flag":
            target = cond.get("target")
            key = cond["key"]
            value = cond["value"]
            if target:
                flags = self.runtime_characters.get(target, {}).get("flags", {})
            else:
                flags = self.global_flags
            return flags.get(key) == value
        elif cond_type == "global_flag":
            key = cond["key"]
            op = cond.get("operator", "==")
            value = cond["value"]
            current = self.global_flags.get(key)
            if current is None:
                return False
            return self.compare(current, op, value)
        return False

    def apply_effect(self, effect):
        etype = effect.get("type")
        if etype == "add_attribute":
            target = effect["target"]
            attr = effect["attribute"]
            value = effect["value"]
            self.runtime_characters[target]["attributes"][attr] = \
                self.runtime_characters[target]["attributes"].get(attr, 0) + value
        elif etype == "set_attribute":
            target = effect["target"]
            attr = effect["attribute"]
            value = effect["value"]
            self.runtime_characters[target]["attributes"][attr] = value
        elif etype == "set_flag":
            target = effect.get("target")
            key = effect["key"]
            value = effect["value"]
            if target:
                self.runtime_characters[target]["flags"][key] = value
            else:
                self.global_flags[key] = value
        elif etype == "set_global_flag":
            key = effect["key"]
            value = effect["value"]
            self.global_flags[key] = value
        elif etype == "add_global_flag":
            key = effect["key"]
            value = effect["value"]
            self.global_flags[key] = self.global_flags.get(key, 0) + value

    def add_history(self, text, choice_text=None):
        if text:
            self.history.append(text)
        if choice_text:
            self.history.append(f"→ {choice_text}")

    def show_history(self):
        print("\n" + "=" * 50)
        print("回忆片段（最近 {} 条）：".format(self.RECALL_SIZE))
        recent = self.history[-self.RECALL_SIZE:]
        for line in recent:
            print(line)
        print("=" * 50 + "\n")

    def save_to_slot(self, slot, auto=False):
        data = {
            "timestamp": datetime.now().isoformat(),
            "scene_id": self.current_scene,
            "current_scene": self.current_scene,
            "characters": self.runtime_characters,
            "global_flags": self.global_flags,
            "player_vars": self.player_vars,
            "history": self.history,
            "current_scene_start_index": self.current_scene_start_index
        }
        filename = self.save_dir / f"save{slot}.json"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if not auto:
                print(f"存档成功：槽位 {slot} - {data['timestamp']}")
        except Exception as e:
            print(f"存档失败：{e}")

    def auto_save(self):
        # 自动保存时，场景已切换，将起始索引设为当前历史长度
        self.current_scene_start_index = len(self.history)
        self.save_to_slot(0, auto=True)

    def save_game(self):
        print("\n" + "=" * 50)
        print("存档槽位列表：")
        for slot in range(0, self.SAVE_SLOT_COUNT + 1):
            filename = self.save_dir / f"save{slot}.json"
            if filename.exists():
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    timestamp = data.get("timestamp", "未知时间")
                    scene_id = data.get("scene_id", "未知场景")
                    if slot == 0:
                        print(f"  [自动存档] 槽位 0 : {timestamp} - 场景 {scene_id}")
                    else:
                        print(f"  槽位 {slot} : {timestamp} - 场景 {scene_id}")
                except:
                    if slot == 0:
                        print(f"  [自动存档] 槽位 0 : 损坏")
                    else:
                        print(f"  槽位 {slot} : 损坏")
            else:
                if slot == 0:
                    print(f"  [自动存档] 槽位 0 : 空")
                else:
                    print(f"  槽位 {slot} : 空")
        print("=" * 50)
        while True:
            choice = input("请选择存档槽位 (1-{})，直接回车返回：".format(self.SAVE_SLOT_COUNT)).strip()
            if choice == "":
                return
            try:
                slot = int(choice)
                if 1 <= slot <= self.SAVE_SLOT_COUNT:
                    break
                else:
                    print("无效槽位，请重新输入。")
            except ValueError:
                print("请输入数字。")
        filename = self.save_dir / f"save{slot}.json"
        if filename.exists():
            confirm = input(f"槽位 {slot} 已有存档，是否覆盖？(y/n)：").strip().lower()
            if confirm != 'y':
                print("取消存档。")
                return
        self.save_to_slot(slot)

    def load_game(self):
        saves = []
        for slot in range(0, self.SAVE_SLOT_COUNT + 1):
            filename = self.save_dir / f"save{slot}.json"
            if filename.exists():
                try:
                    with open(filename, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    saves.append((slot, data))
                except:
                    continue
        if not saves:
            print("没有找到存档。")
            return False
        print("\n" + "=" * 50)
        print("可用存档：")
        for slot, data in saves:
            timestamp = data.get("timestamp", "未知时间")
            scene_id = data.get("scene_id", "未知场景")
            if slot == 0:
                print(f"  [自动存档] 槽位 0 : {timestamp} - 场景 {scene_id}")
            else:
                print(f"  槽位 {slot} : {timestamp} - 场景 {scene_id}")
        print("=" * 50)
        while True:
            choice = input("请选择要读取的存档槽位 (0-{})，直接回车返回：".format(self.SAVE_SLOT_COUNT)).strip()
            if choice == "":
                return False
            try:
                slot = int(choice)
                if 0 <= slot <= self.SAVE_SLOT_COUNT and any(s == slot for s, _ in saves):
                    break
                else:
                    print("无效槽位或该槽位无存档，请重新输入。")
            except ValueError:
                print("请输入数字。")
        filename = self.save_dir / f"save{slot}.json"
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.current_scene = data["current_scene"]
            self.runtime_characters = data["characters"]
            self.global_flags = data["global_flags"]
            self.player_vars = data.get("player_vars", {})
            self.history = data.get("history", [])
            # 处理历史截断
            if "current_scene_start_index" in data:
                self.current_scene_start_index = data["current_scene_start_index"]
                self.history = self.history[:self.current_scene_start_index]
            else:
                # 旧存档没有该字段，清空历史以保证对应
                self.current_scene_start_index = 0
                self.history = []
            self.show_history()
            return True
        except Exception as e:
            print(f"读档失败：{e}")
            return False

    def handle_common_commands(self, command, valid_options=None):
        if command == "e":
            sys.exit(0)
        elif command == "s":
            self.save_game()
            return True
        elif command == "l":
            if self.load_game():
                return "load_success"
            return True
        elif command == "a":
            self.auto_play = not self.auto_play
            state = "开启" if self.auto_play else "关闭"
            print(f"自动播放已{state}")
            return True
        elif command == "h":
            self.show_history()
            return True
        return False

    def auto_play_wait(self):
        if not HAS_MSVCRT:
            time.sleep(self.AUTO_PLAY_INTERVAL)
            return True
        start = time.time()
        while time.time() - start < self.AUTO_PLAY_INTERVAL:
            if msvcrt.kbhit():
                msvcrt.getch()
                self.auto_play = False
                print("\n（自动播放已取消）")
                return False
            time.sleep(0.05)
        return True

    def wait_for_continue(self):
        while True:
            if self.auto_play:
                if self.auto_play_wait():
                    return True
            # 手动等待：无提示，直接读取回车
            user_input = input().strip().lower()
            if user_input == "":
                return True
            cmd_result = self.handle_common_commands(user_input)
            if cmd_result == "load_success":
                return False
            elif cmd_result is True:
                continue
            else:
                print("按回车继续，或输入 s/l/a/h/e")

    def show_scene(self):
        scene = self.scenes.get(self.current_scene)
        if not scene:
            print(f"错误：场景 '{self.current_scene}' 不存在！")
            self.current_scene = "end"
            return

        # 记录当前场景起始历史索引
        self.current_scene_start_index = len(self.history)

        raw_text = scene.get("text", "")
        segments = [seg for seg in raw_text.split('\n') if seg.strip() != ""]

        for seg in segments:
            seg_display = self.display_text_with_inputs(seg)
            self.add_history(seg_display)
            # 自动播放模式下，段落后自动换行，避免下一段接在同一行
            if self.auto_play:
                print()
            if not self.wait_for_continue():
                return

        valid_options = []
        for opt in scene.get("options", []):
            if all(self.check_condition(cond) for cond in opt.get("conditions", [])):
                valid_options.append(opt)

        if valid_options:
            while True:
                # 显示选项前确保换行
                print()
                for i, opt in enumerate(valid_options, 1):
                    print(f"{i}. {self.replace_vars(opt['text'])}")
                choice = input().strip().lower()
                if choice == "":
                    continue
                cmd_result = self.handle_common_commands(choice)
                if cmd_result == "load_success":
                    return
                elif cmd_result is True:
                    continue
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(valid_options):
                        chosen = valid_options[idx]
                        break
                    else:
                        print(f"请输入 1-{len(valid_options)} 之间的数字")
                except ValueError:
                    print("请输入数字选择选项，或输入 s/l/a/h/e")
            self.add_history("", self.replace_vars(chosen['text']))
            for effect in chosen.get("effects", []):
                self.apply_effect(effect)
            self.current_scene = chosen.get("next_scene", "end")
            self.auto_save()
        else:
            self.current_scene = scene.get("next_scene", "end")
            self.auto_save()

    def show_main_menu(self):
        """显示主界面（带方框美化）"""
        border = "+" + "-" * 52 + "+"
        print(border)
        print("|" + "欢迎游玩！".center(47) + "|")
        print("|" + "操作说明：".center(47) + "|")
        print("|" + "  - 纯对话时按回车继续".ljust(43) + "|")
        print("|" + "  - 出现选项时输入数字选择".ljust(41) + "|")
        print("|" + "  - 输入 's' 手动存档（可选择槽位）".ljust(39) + "|")
        print("|" + "  - 输入 'l' 读档".ljust(48) + "|")
        print("|" + "  - 输入 'a' 切换自动播放（间隔{}秒）".format(self.AUTO_PLAY_INTERVAL).ljust(39) + "|")
        print("|" + "  - 输入 'h' 查看最近对话回忆".ljust(42) + "|")
        print("|" + "  - 输入 'e' 退出游戏".ljust(46) + "|")
        print(border)

    def run(self):
        # 显示主界面
        self.show_main_menu()
        # 主界面循环
        while True:
            print("\n按回车开始游戏，或输入 s/l/e：", end='', flush=True)
            user_input = input().strip().lower()
            if user_input == "":
                # 开始游戏（新游戏或继续当前状态）
                break
            elif user_input == "e":
                sys.exit(0)
            elif user_input == "s":
                self.save_game()
                continue
            elif user_input == "l":
                if self.load_game():
                    # 读档成功，进入游戏
                    break
                else:
                    continue
            else:
                print("无效输入，请重新选择。")
                continue

        # 进入正文游戏循环
        while self.current_scene != "end":
            self.show_scene()
        self.type_text("=== 游戏结束 ===")
        input("\n按回车键退出...")

if __name__ == "__main__":
    try:
        game = GalgameEngine()
        game.run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("\n发生错误，按回车键退出...")