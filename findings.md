# Findings & Decisions

## Requirements
- 重新设计 static/ 下的前端界面（index.html, styles.css, app.js）
- 保留所有现有功能：对话（快速/流式）、AIOps 诊断、文件上传、历史会话、Markdown 渲染、代码高亮
- 需要具有鲜明的视觉个性，避免 "AI 感" 的通用设计
- 产品定位：企业级智能运维助手

## Research Findings
- 现有界面采用浅色主题，左侧边栏 + 右侧对话区的双栏布局
- 使用 marked.js 做 Markdown 渲染，highlight.js 做代码高亮
- API 端点：/api/chat, /api/chat_stream, /api/aiops, /api/upload, /api/chat/clear, /api/chat/session/{id}

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 暗色主题 + 科技感视觉风格 | 运维工具的传统，同时能营造沉浸式对话体验 |
| CSS-only 动画优先 | 减少 JS 依赖，性能更好 |
| 保留 CDN 依赖（marked, highlight.js） | 功能不变，不需要更换 |
| 独立 HTML/CSS/JS 文件 | 保持与现有架构一致，FastAPI 直接 serve static |
| 琥珀色(Amber) + 青色(Cyan) 点缀色 | Amber 象征终端/告警灯，Cyan 象征数据流，符合运维工具调性 |
| DM Sans (标题) + JetBrains Mono (终端) | 不落俗套的字体组合，DMSans 比 Inter 更有性格 |
| 输入框终端提示符 ❯ | 强化命令行/运维操作感 |
| 网格背景 + 渐暗晕影 | 增加界面深度，避免暗色主题显得扁平 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
|       |            |

## Resources
- 项目根目录: C:\Users\26344\Desktop\super_biz_agent_py-release-2026-03-21
- 备份目录: C:\Users\26344\Desktop\super_biz_agent_py-BACKUP-2026-04-26
- API 文档: http://localhost:9900/docs
- 现有 static/ 文件: index.html (7752B), styles.css (21363B), app.js (70979B)
