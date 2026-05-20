/**
 * 初中数学智能教学系统 - 主应用
 * 单页应用(SPA)架构
 */

// ==================== 配置 ====================
const API_BASE = 'http://localhost:8000';

// 获取 APP 元素的辅助函数
function getAPP() {
    const app = document.getElementById('app');
    if (!app) {
        console.error('[ERROR] APP element not found!');
    }
    return app;
};

// ==================== 状态管理 ====================
const state = {
    sessionId: localStorage.getItem('sessionId') || null,
    currentUser: null,
    currentPage: 'login'
};

// ==================== 路由配置 ====================
const routes = {
    '/login': '/teacher/frontend/pages/login.html',
    '/teacher': '/teacher/frontend/pages/teacher.html'
};

// ==================== 工具函数 ====================
/**
 * HTML转义函数 - 转义HTML特殊字符，但保留LaTeX公式
 * @param {string} text - 需要转义的文本
 * @returns {string} - 转义后的HTML安全文本
 */
function escapeHtml(text) {
    if (typeof text !== 'string') return '';

    // 先保护LaTeX公式（支持所有 MathJax 识别的数学定界符）
    const latexBlocks = [];
    // 匹配优先级：$$...$$ > \[...\] > \(...\) > $...$ > \begin{...}...\end{...}
    const mathRegex = /\$\$[\s\S]*?\$\$|\\\[.*?\\\]|\\$$.*?\\$$|\$[^\$\n]+?\$|\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}/g;
    let protectedText = text.replace(mathRegex, (match) => {
        latexBlocks.push(match);
        return `%%LATEX_${latexBlocks.length - 1}%%`;
    });

    // 转义HTML特殊字符
    const div = document.createElement('div');
    div.textContent = protectedText;
    let result = div.innerHTML;

    // 恢复LaTeX公式
    result = result.replace(/%%LATEX_(\d+)%%/g, (_, idx) => latexBlocks[parseInt(idx)]);

    return result;
}

/**
 * 转义HTML属性值
 * @param {string} text - 需要转义的文本
 * @returns {string} - 转义后的安全属性值
 */
function escapeHtmlAttr(text) {
    if (typeof text !== 'string') return '';
    return text
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

/**
 * 智能格式化课程内容（P1方案：前端兜底格式化）
 * @param {string} text - 需要格式化的文本
 * @returns {string} - 格式化后的文本
 *
 * 功能说明：
 * 1. 检测内容是否已有足够的换行符（每100字符至少1个换行）
 * 2. 如果已格式化，保持原样
 * 3. 如果未格式化，应用智能格式规则
 * 4. 处理数学符号和LaTeX公式
 */
function smartFormat(text) {
    if (typeof text !== 'string') return '';

    // 1. 处理 JSON 中被转义的换行符
    let result = text.replace(/\\n/g, '\n');

    // 2. 提取并保护所有数学公式块（防止后续格式化破坏公式）
    //    所有公式由 MathJax 统一渲染，不再手动处理 LaTeX 命令
    const mathBlocks = [];
    const mathRegex = /\$\$[\s\S]*?\$\$|\\\[.*?\\\]|\\$$.*?\\$$|\$[^\$\n]+?\$|\\begin\{[^}]+\}[\s\S]*?\\end\{[^}]+\}/g;
    result = result.replace(mathRegex, (match) => {
        mathBlocks.push(match);
        return `%%MATH_${mathBlocks.length - 1}%%`;
    });

    // 3. 转义 HTML（仅对非公式部分）
    const div = document.createElement('div');
    div.textContent = result;
    result = div.innerHTML;

    // 4. 文本格式化（只处理纯文本，不碰数学公式）

    // 4.1 处理【小标题】
    result = result.replace(/【([^】\n]{1,30})】/g, function(match, p1) {
        if (p1.length <= 30 && !p1.includes('\n')) {
            return '\n\n<div style="color: #2a78ff; font-weight: 600; margin: 16px 0 8px 0;">【' + p1 + '】</div>\n\n';
        }
        return match;
    });

    // 4.2 处理 Markdown 标题（#### > ### > ## 顺序，避免误匹配）
    result = result.replace(/^#### (.+)$/gm, '\n<div style="font-weight: 600; font-size: 14px; margin: 10px 0 4px 0; color: #333;">$1</div>\n');
    result = result.replace(/^### (.+)$/gm, '\n<div style="font-weight: 600; font-size: 15px; margin: 12px 0 6px 0; color: #333;">$1</div>\n');
    result = result.replace(/^## (.+)$/gm, '\n<div style="font-weight: 700; font-size: 16px; margin: 14px 0 8px 0; color: #2a78ff;">$1</div>\n');

    // 4.3 处理 ===分页===
    result = result.replace(/===分页===/g, '\n\n<hr style="border: none; border-top: 1px dashed #ccc; margin: 16px 0;">\n\n');

    // 4.4 处理序号列表
    result = result.replace(/\n(\d+)[.、]\s*/g, '\n<br><span style="margin-left: 8px;">$1.</span> ');
    result = result.replace(/^(\d+)[.、]\s*/gm, '<br><span style="margin-left: 8px;">$1.</span> ');

    // 4.5 处理中文序号
    result = result.replace(/\n([一二三四五六七八九十]+)[、。]\s*/g, '\n<br><strong>$1、</strong> ');
    result = result.replace(/^([一二三四五六七八九十]+)[、。]\s*/gm, '<br><strong>$1、</strong> ');

    // 4.6 处理圆圈数字序号
    result = result.replace(/[①②③④⑤⑥⑦⑧⑨⑩]/g, '<br><span style="margin-left: 8px;">$&</span> ');

    // 4.7 处理 Markdown 粗体（必须在斜体之前，避免 ** 被 * 先匹配）
    result = result.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // 4.8 处理 Markdown 斜体（只匹配成对的单 *，排除 ** 残留）
    result = result.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');
    // 4.9 处理 Markdown 无序列表（行首 "- "，排除负数 "-3"）
    result = result.replace(/^- (.+)$/gm, '<br><span style="margin-left: 8px;">•</span> $1');
    result = result.replace(/\n- (.+)/g, '<br><span style="margin-left: 8px;">•</span> $1');
    // 4.10 处理 Markdown 引用块（行首 "> "）
    result = result.replace(/^&gt; (.+)$/gm, '<div style="border-left: 3px solid #2a78ff; padding: 8px 12px; margin: 8px 0; background: #f0f4ff; border-radius: 4px;">$1</div>');
    result = result.replace(/\n&gt; (.+)/g, '<div style="border-left: 3px solid #2a78ff; padding: 8px 12px; margin: 8px 0; background: #f0f4ff; border-radius: 4px;">$1</div>');

    // 4.11 处理换行符
    result = result.replace(/\n\n+/g, '</p><p style="margin: 8px 0;">');
    result = result.replace(/\n/g, '<br>');

    // 4.12 包装段落
    result = '<p style="margin: 8px 0;">' + result + '</p>';

    // 4.13 清理多余标签
    result = result.replace(/<p[^>]*>\s*<\/p>/g, '');
    result = result.replace(/<p[^>]*><br>/g, '<p style="margin: 8px 0;">');
    result = result.replace(/<br><\/p>/g, '</p>');
    result = result.replace(/<br>\s*<br>/g, '<br>');
    result = result.replace(/<div([^>]*)>\s*<br>/g, '<div$1>');
    result = result.replace(/<br>\s*<\/div>/g, '</div>');

    // 5. 还原数学公式块（完整保留 LaTeX，交由 MathJax 渲染）
    result = result.replace(/%%MATH_(\d+)%%/g, (_, idx) => mathBlocks[parseInt(idx)]);

    // 6. 修复 align/gather/cases 等多行数学环境中的换行符
    //    LLM 输出的 \begin{align*} 中行尾可能是 \n 而非 \\，
    //    MathJax 需要 \\ 作为换行命令。只给缺少 \\ 的行补上。
    result = result.replace(/(\\begin\{(?:align|gather|cases|aligned|split|multline)\*?\})([\s\S]*?)(\\end\{(?:align|gather|cases|aligned|split|multline)\*?\})/g,
        function(wholeMatch, begin, body, end) {
            const lines = body.split('\n');
            const fixed = lines.map((line, i) => {
                const trimmed = line.trimEnd();
                // 第一行和最后一行（空行）不处理
                if (i === 0 || i === lines.length - 1) return line;
                if (trimmed === '') return line;
                // 已经以 \\ 结尾的行不重复添加
                if (trimmed.endsWith('\\\\')) return line;
                return trimmed + ' \\\\';
            });
            return begin + fixed.join('\n') + end;
        }
    );

    return result;
}

/**
 * 显示提示消息
 * @param {string} message - 消息内容
 * @param {string} type - 消息类型: 'success', 'error', 'info', 'warning'
 * @param {Object} options - 额外选项
 * @param {number} options.duration - 显示时长（毫秒），默认 3000
 * @param {Array} options.actions - 操作按钮数组 [{text: '按钮文字', onClick: () => {}, primary: true}]
 */
function showToast(message, type = 'info', options = {}) {
    const { duration = 3000, actions = [] } = options;

    // 移除已有的 toast
    const existingToasts = document.querySelectorAll('.toast');
    existingToasts.forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    // 消息内容容器
    const contentContainer = document.createElement('div');
    contentContainer.className = 'toast-content';
    contentContainer.textContent = message;
    toast.appendChild(contentContainer);

    // 添加操作按钮
    if (actions.length > 0) {
        const actionsContainer = document.createElement('div');
        actionsContainer.className = 'toast-actions';

        actions.forEach(action => {
            const button = document.createElement('button');
            button.className = `toast-action ${action.primary ? 'toast-action-primary' : ''}`;
            button.textContent = action.text;
            button.onclick = () => {
                if (action.onClick) {
                    action.onClick();
                }
                toast.remove();
            };
            actionsContainer.appendChild(button);
        });

        toast.appendChild(actionsContainer);
    }

    document.body.appendChild(toast);

    // 自动隐藏（如果有操作按钮，延长显示时间）
    if (actions.length === 0) {
        setTimeout(() => toast.remove(), duration);
    } else {
        setTimeout(() => {
            if (toast.parentElement) {
                toast.classList.add('toast-fading');
                setTimeout(() => toast.remove(), 300);
            }
        }, Math.max(duration, 5000));
    }
}

/**
 * 成功提示快捷函数（带操作引导）
 */
function showToastWithActions(message, actions) {
    return showToast(message, 'success', { actions });
}

/**
 * 滚动到预览区域
 */
function scrollToPreview() {
    const previewSection = document.getElementById('previewSection');
    if (previewSection) {
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// ==================== API 请求 ====================
// 友好错误消息映射
const ERROR_MESSAGES = {
    // 网络错误
    'Failed to fetch': '网络连接失败，请检查网络连接',
    'Failed to load resource': '加载失败，请检查网络连接',
    'NetworkError': '网络错误，请检查网络连接',

    // HTTP 状态码
    '400': '请求参数错误，请检查输入内容',
    '401': '登录已过期，请重新登录',
    '403': '没有权限执行此操作',
    '404': '请求的资源不存在',
    '409': '数据冲突，请刷新页面后重试',
    '422': '请求数据格式错误，请检查输入',
    '429': '请求过于频繁，请稍后再试',
    '500': '服务器内部错误，请稍后重试',
    '502': '服务器暂时不可用，请稍后重试',
    '503': '服务维护中，请稍后访问',
    '504': '服务器响应超时，请稍后重试',

    // 业务错误
    'Invalid credentials': '用户名或密码错误',
    'Session not found': '会话已过期，请重新登录',
    'Session expired': '会话已过期，请重新登录',
    'Course not found': '课程不存在',
    'Chapter not found': '章节不存在',
    'Invalid request': '请求格式错误',
    'Permission denied': '权限不足',
    'Resource not found': '资源不存在',
    'Task not found': '任务不存在或已过期',

    // LLM 相关错误
    'LLM API error': 'AI 服务暂时不可用，请稍后重试',
    'Content generation failed': '内容生成失败，请重试',
    'Invalid LLM response': 'AI 返回数据格式错误，请重试',
    'Rate limit exceeded': 'AI 服务调用次数过多，请稍后重试',

    // 文件操作错误
    'File not found': '文件不存在',
    'File too large': '文件过大，请选择小于 100MB 的文件',
    'Invalid file type': '文件类型不支持',
    'Upload failed': '文件上传失败，请重试',

    // 视频生成错误
    'Video generation failed': '视频生成失败，请重试',
    'No content to generate video': '没有可生成视频的内容',
    'Video task already in progress': '视频生成任务正在进行中'
};

/**
 * 获取友好的错误消息
 * @param {Object|string} error - 错误对象或错误消息
 * @returns {string} 友好的中文错误消息
 */
function getFriendlyErrorMessage(error) {
    let errorMessage = '';

    if (typeof error === 'string') {
        errorMessage = error;
    } else if (error && error.message) {
        errorMessage = error.message;
    } else if (error && error.detail) {
        errorMessage = error.detail;
    } else {
        errorMessage = String(error);
    }

    // 检查是否有匹配的错误消息
    for (const [key, value] of Object.entries(ERROR_MESSAGES)) {
        if (errorMessage.includes(key)) {
            return value;
        }
    }

    // 如果没有匹配的，返回原始消息（如果已经是中文）或默认消息
    if (/[\u4e00-\u9fa5]/.test(errorMessage)) {
        return errorMessage;
    }

    return '操作失败，请稍后重试';
}

async function apiRequest(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    if (state.sessionId) {
        url += (url.includes('?') ? '&' : '?') + `session_id=${state.sessionId}`;
    }

    const response = await fetch(API_BASE + url, {
        ...defaultOptions,
        ...options,
    });

    if (!response.ok) {
        let errorData;
        try {
            errorData = await response.json();
        } catch {
            errorData = { detail: `HTTP ${response.status}` };
        }

        // 特殊处理401错误：清除session并跳转登录页
        if (response.status === 401) {
            console.warn('[apiRequest] Session已过期，清除并跳转登录页');
            state.sessionId = null;
            state.currentUser = null;
            localStorage.removeItem('sessionId');
            showToast('登录已过期，请重新登录', 'info');
            setTimeout(() => {
                window.location.href = '/';
            }, 1500);
            throw new Error('登录已过期，请重新登录');
        }

        throw new Error(getFriendlyErrorMessage(errorData));
    }

    return response.json();
}

// ==================== 页面加载器 ====================
// HTML缓存版本号（每次修改HTML后递增）
const HTML_VERSION = 'v24';

async function loadPage(pageName) {
    try {
        // 添加版本号绕过浏览器缓存
        const url = pageName.includes('?') ? `${pageName}&${HTML_VERSION}` : `${pageName}?${HTML_VERSION}`;
        const response = await fetch(url);
        const html = await response.text();


        // 先设置 HTML
        const APP = getAPP();
        if (!APP) return;
        APP.innerHTML = html;

        // 手动执行页面中的 script 标签
        const scripts = APP.querySelectorAll('script');
        scripts.forEach(script => {
            const newScript = document.createElement('script');
            if (script.src) {
                newScript.src = script.src;
            } else {
                newScript.textContent = script.textContent;
            }
            // 复制所有属性
            Array.from(script.attributes).forEach(attr => {
                if (attr.name !== 'src' && attr.name !== 'type') {
                    newScript.setAttribute(attr.name, attr.value);
                }
            });
            script.parentNode.replaceChild(newScript, script);
        });

        initPageScripts(pageName);
    } catch (error) {
        console.error('页面加载失败:', error);
        const errorApp = getAPP();
        if (errorApp) {
            errorApp.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
        }
    }
}

function initPageScripts(pageName) {
    if (pageName.includes('login.html')) {
        initLoginPage();
    } else if (pageName.includes('student.html')) {
        initStudentPage();
    } else if (pageName.includes('teacher.html')) {
        initTeacherPage();
    } else if (pageName.includes('course_catalog.html')) {
        // 课程目录页面有内联脚本，无需额外初始化
    } else if (pageName.includes('course_learning.html')) {
        // 课程学习页面有内联脚本，无需额外初始化
    }
}

// ==================== 路由导航 ====================
function navigate(route) {
    if (!routes[route]) {
        console.error('路由不存在:', route);
        return;
    }

    state.currentPage = route;
    loadPage(routes[route]);
}

// ==================== 检查登录状态 ====================
async function checkAuth() {
    if (!state.sessionId) {
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
        return;
    }

    try {
        const response = await apiRequest('/api/auth/me');
        state.currentUser = response.user;

        // 根据角色跳转
        if (state.currentUser.role === 'teacher') {
            navigate('/teacher');
        } else {
            navigate('/student');
        }
    } catch (error) {
        // 会话无效，返回登录页
        state.sessionId = null;
        state.currentUser = null;
        localStorage.removeItem('sessionId');
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
    }
}

// ==================== 登出 ====================
function logout() {
    apiRequest('/api/auth/logout').finally(() => {
        state.sessionId = null;
        state.currentUser = null;
        localStorage.removeItem('sessionId');
        // 跳转到根路径的统一登录页面
        window.location.href = '/';
    });
}

// ==================== 全局函数（登录页使用） ====================
// 这些函数需要在页面加载前就可用

window.openModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        modal.style.display = 'flex';
    }
};

window.closeModal = function(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        modal.style.display = 'none';
    }
};

window.switchModal = function(currentModal, targetModal) {
    closeModal(currentModal);
    setTimeout(() => openModal(targetModal), 100);
};

window.scrollToSection = function(event, sectionId) {
    event.preventDefault();
    const section = document.getElementById(sectionId);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};

// ==================== 登录页逻辑 ====================
function initLoginPage() {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');

    // 定义模态框操作函数
    const openModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('show');
            modal.style.display = 'flex';
        }
    };

    const closeModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('show');
            modal.style.display = 'none';
        }
    };

    const switchModal = function(currentModal, targetModal) {
        closeModal(currentModal);
        setTimeout(() => openModal(targetModal), 100);
    };

    const scrollToSection = function(event, sectionId) {
        if (event) event.preventDefault();
        const section = document.getElementById(sectionId);
        if (section) {
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    };

    // 绑定模态框打开按钮
    const modalButtons = document.querySelectorAll('[data-modal]');
    modalButtons.forEach((btn, index) => {
        btn.addEventListener('click', (e) => {
            const modalId = btn.getAttribute('data-modal');
            openModal(modalId);
        });
    });

    // 绑定关闭按钮
    const closeButtons = document.querySelectorAll('[data-close]');
    closeButtons.forEach((btn, index) => {
        btn.addEventListener('click', (e) => {
            const modalId = btn.getAttribute('data-close');
            closeModal(modalId);
        });
    });

    // 绑定滚动链接
    const scrollLinks = document.querySelectorAll('[data-scroll]');
    scrollLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            const sectionId = link.getAttribute('data-scroll');
            scrollToSection(e, sectionId);
        });
    });

    // 绑定切换模态框链接
    const switchLinks = document.querySelectorAll('[data-switch]');
    switchLinks.forEach((link) => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const targets = link.getAttribute('data-switch').split(',');
            switchModal(targets[0], targets[1]);
        });
    });

    // 点击模态框背景关闭
    setTimeout(() => {
        document.querySelectorAll('.modal').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    closeModal(modal.id);
                }
            });
        });
    }, 100);

    // 登录表单
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;

            try {
                const response = await apiRequest('/api/auth/login', {
                    method: 'POST',
                    body: JSON.stringify({ username, password })
                });

                state.sessionId = response.session_id;
                state.currentUser = response.user;
                localStorage.setItem('sessionId', response.session_id);

                closeModal('loginModal');
                showToast('登录成功！', 'success');
                setTimeout(() => {
                    // 登录成功后跳转到对应的完整页面
                    if (response.user.role === 'teacher') {
                        window.location.href = '/teacher/frontend/index.html';
                    } else {
                        window.location.href = '/student/frontend/index.html';
                    }
                }, 500);
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    }

    // 注册表单
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const role = document.getElementById('registerRole').value;
            const username = document.getElementById('registerUsername').value.trim();
            const password = document.getElementById('registerPassword').value;
            const email = document.getElementById('registerEmail').value.trim();

            // 客户端验证
            if (username.length < 2 || username.length > 20) {
                showToast('用户名长度必须在2-20个字符之间', 'error');
                return;
            }

            if (password.length < 6) {
                showToast('密码长度至少为6位', 'error');
                return;
            }

            const data = {
                username: username,
                password: password,
                role: role,
                email: email
            };

            if (role === 'student') {
                const studentId = document.getElementById('registerStudentId').value.trim();
                const className = document.getElementById('registerClass').value.trim();

                if (!studentId) {
                    showToast('请输入学号', 'error');
                    return;
                }
                if (!className) {
                    showToast('请输入班级', 'error');
                    return;
                }

                data.student_id = studentId;
                data.class_name = className;
            }

            try {
                // 禁用提交按钮，防止重复提交
                const submitBtn = registerForm.querySelector('button[type="submit"]');
                const originalText = submitBtn.textContent;
                submitBtn.disabled = true;
                submitBtn.textContent = '注册中...';

                const response = await apiRequest('/api/auth/register', {
                    method: 'POST',
                    body: JSON.stringify(data)
                });

                showToast('注册成功！请登录', 'success');
                closeModal('registerModal');
                openModal('loginModal');
                registerForm.reset();
            } catch (error) {
                showToast(error.message || '注册失败，请稍后重试', 'error');
            } finally {
                // 恢复提交按钮
                const submitBtn = registerForm.querySelector('button[type="submit"]');
                submitBtn.disabled = false;
                submitBtn.textContent = '注册';
            }
        });

        // 角色切换时显示/隐藏学生字段
        const roleSelect = document.getElementById('registerRole');
        const studentFields = document.getElementById('studentFields');

        if (roleSelect && studentFields) {
            // 初始化状态
            studentFields.style.display = roleSelect.value === 'student' ? 'block' : 'none';

            roleSelect.addEventListener('change', () => {
                studentFields.style.display = roleSelect.value === 'student' ? 'block' : 'none';
            });
        }
    }
}

// ==================== 学生端逻辑 ====================
function initStudentPage() {
    // 设置用户信息
    const userInfo = document.querySelector('.user-name');
    if (userInfo && state.currentUser) {
        userInfo.textContent = state.currentUser.username;
    }

    // 加载课程
    loadStudentCourses();

    // 导航事件
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            const target = item.dataset.target;
            document.querySelectorAll('.content-page').forEach(p => p.classList.remove('active'));
            document.getElementById(target).classList.add('active');

            // 加载对应内容
            if (target === 'courses') loadStudentCourses();
            else if (target === 'join-class') loadJoinClassPage();
        });
    });

    // 登出按钮
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
}

async function loadStudentCourses() {
    const container = document.getElementById('coursesList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/student/courses');
        const courses = response.courses || [];

        if (courses.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📚</div>
                    <div class="empty-text">暂无课程，请联系老师分享课程</div>
                </div>
            `;
            return;
        }

        container.innerHTML = '<div class="courses-grid">' + courses.map(course => `
            <div class="course-card">
                <div class="course-card-header">
                    <div class="course-card-icon">📖</div>
                    <div class="course-card-info">
                        <div class="course-card-title">${(course.title || (course.grade || '') + ' ' + (course.chapter || '')).replace(/'/g, '&#39;')}</div>
                        <div class="course-card-meta">
                            <span class="meta-tag">${course.grade || '未分类'}</span>
                            <span class="meta-tag">${Object.keys(course.sections || {}).length} 章节</span>
                        </div>
                    </div>
                </div>
                <div class="course-card-body">
                    <p class="course-description">
                        ${course.description || (course.sections && Object.keys(course.sections).length > 0 ? Object.keys(course.sections).join('、') : '暂无简介')}
                    </p>
                    ${course.progress !== undefined ? `
                        <div class="course-progress-mini">
                            <div class="progress-bar-mini">
                                <div class="progress-fill-mini" style="width: ${course.progress}%"></div>
                            </div>
                            <span class="progress-text-mini">${course.progress}%</span>
                        </div>
                    ` : ''}
                </div>
                <div class="course-card-footer">
                    <span class="course-date">
                        ${course.created_at ? new Date(course.created_at).toLocaleDateString() : ''}
                    </span>
                    <div class="course-actions">
                        <button class="btn btn-primary btn-enter-course"
                                data-course-id="${course.id}"
                                data-course-title="${course.title}">
                            进入学习 →
                        </button>
                    </div>
                </div>
            </div>
        `).join('') + '</div>';

        // 绑定课程卡片按钮事件（学生端只有"进入学习"按钮）
        container.querySelectorAll('.btn-enter-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                enterCourseCatalog(courseId);
            });
        });

    } catch (error) {
        console.error('加载课程失败:', error);
        showToast(error.message, 'error');
        container.innerHTML = `<div class="empty-state"><div class="empty-text">加载失败，请重试</div></div>`;
    }
}

// 进入课程目录（重定向到学生端）
function enterCourseCatalog(courseId) {
    // 教师端预览学生视图：重定向到学生端URL
    window.location.href = `/student/index.html#/student/catalog/${courseId}`;
}

// 查看课程详情（保留旧函数兼容性）
// viewCourse 函数已移至第1891行，避免重复定义导致功能失效

// ==================== 学生加入班级 ====================
async function loadJoinClassPage() {
    loadMyClass();

    // 初始化搜索表单
    const searchForm = document.getElementById('searchClassForm');
    if (searchForm && !searchForm.dataset.initialized) {
        searchForm.dataset.initialized = 'true';
        searchForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const keyword = document.getElementById('searchKeyword').value.trim();
            await searchClasses(keyword);
        });
    }

    // 初始加载所有班级
    searchClasses('');
}

async function loadMyClass() {
    const container = document.getElementById('myClassInfo');
    if (!container) return;

    try {
        const user = state.currentUser;
        if (!user || !user.class) {
            container.innerHTML = '<p style="color: #999;">尚未加入任何班级</p>';
            return;
        }

        // 查找用户的班级
        const response = await apiRequest('/api/classes');
        const myClass = response.classes?.find(c => c.name === user.class);

        if (!myClass) {
            container.innerHTML = '<p style="color: #999;">尚未加入任何班级</p>';
            return;
        }

        container.innerHTML = `
            <div style="padding: 16px; background: #f5f5f5; border-radius: 8px;">
                <h4 style="margin-bottom: 8px;">${myClass.name}</h4>
                <div style="color: #666; margin-bottom: 12px;">
                    ${myClass.grade ? `年级: ${myClass.grade}` : ''}
                    ${myClass.description ? `<br>描述: ${myClass.description}` : ''}
                </div>
                <button class="btn btn-secondary" onclick="leaveClass('${myClass.id}', '${myClass.name}')">退出班级</button>
            </div>
        `;
    } catch (error) {
        container.innerHTML = '<p style="color: #f00;">加载班级信息失败</p>';
    }
}

async function searchClasses(keyword) {
    const container = document.getElementById('searchResults');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest(`/api/classes?keyword=${encodeURIComponent(keyword)}`);
        const classes = response.classes || [];

        if (classes.length === 0) {
            container.innerHTML = `
                <div class="card">
                    <p style="color: #999; text-align: center;">未找到匹配的班级</p>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="card">
                <h3 style="margin-bottom: 16px;">搜索结果 (${classes.length})</h3>
                ${classes.map(cls => `
                    <div style="padding: 12px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <div style="font-weight: 600; margin-bottom: 4px;">${cls.name}</div>
                            <div style="color: #666; font-size: 14px;">
                                ${cls.grade ? `年级: ${cls.grade}` : ''} ${cls.grade && cls.description ? ' | ' : ''} ${cls.description || ''}
                                <br>学生: ${cls.student_count || 0} 人
                            </div>
                        </div>
                        ${cls.joined
                            ? '<span style="color: #4CAF50;">已加入</span>'
                            : `<button class="btn btn-primary" onclick="joinClass('${cls.id}', '${cls.name}')">加入</button>`
                        }
                    </div>
                `).join('')}
            </div>
        `;
    } catch (error) {
        container.innerHTML = '<p style="color: #f00;">搜索失败</p>';
    }
}

async function joinClass(classId, className) {
    try {
        await apiRequest('/api/student/class/join', {
            method: 'POST',
            body: JSON.stringify({ class_id: classId })
        });
        showToast(`已加入 ${className}`, 'success');
        loadJoinClassPage();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function leaveClass(classId, className) {
    if (!confirm(`确定要退出班级"${className}"吗？`)) return;

    try {
        await apiRequest('/api/student/class/leave', {
            method: 'POST',
            body: JSON.stringify({ class_id: classId })
        });
        showToast('已退出班级', 'success');
        loadJoinClassPage();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== 教师端逻辑 ====================
function initTeacherPage() {
    // 设置用户信息
    const userInfo = document.querySelector('.user-name');
    if (userInfo && state.currentUser) {
        userInfo.textContent = state.currentUser.username;
    }

    // 加载课程
    loadTeacherCourses();

    // 初始化班级管理表单（在导航事件之前初始化，确保表单绑定）
    initClassForm();

    // 导航事件
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');

            const target = item.dataset.target;
            document.querySelectorAll('.content-page').forEach(p => p.classList.remove('active'));
            document.getElementById(target).classList.add('active');

            // 加载对应内容
            if (target === 'courses') loadTeacherCourses();
            else if (target === 'generate') showGeneratePage();
            else if (target === 'classes') loadClasses();
            else if (target === 'students') loadStudents();
            else if (target === 'lessonPlans') loadTeacherLessonPlans();
        });
    });

    // 登出按钮
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    // 课程生成表单
    const generateForm = document.getElementById('generateForm');
    if (generateForm) {
        initGenerateForm();
    }
}

// ==================== 自动视频生成（课程生成后触发）====================
// 全局变量：存储自动触发的视频生成任务ID
let autoVideoTaskId = null;

async function startVideoGeneration(courseId) {
    try {
        // 获取课程详情
        const courseResponse = await apiRequest(`/api/teacher/courses`);
        const course = courseResponse.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 构建课程内容
        let content = '';
        if (course.content) {
            if (course.content.sections) {
                const sections = course.content.sections;
                content = Object.entries(sections).map(([key, value]) =>
                    `${key}\n${value}`
                ).join('\n\n');
            } else if (course.content.full_text) {
                content = course.content.full_text;
            }
        }

        if (!content) {
            content = `课程标题: ${course.title}\n年级: ${course.grade}\n章节: ${course.chapter}`;
        }

        // 调用视频生成API
        const response = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: course.id,
                title: course.title,
                content: content
            })
        });

        autoVideoTaskId = response.task_id;
        showToast('视频生成已启动，您可以在当前页面查看进度', 'info');

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');
    }
}

// 从 task_id 直接启动视频生成（完成后自动保存课程）
async function startVideoGenerationWithTaskId(taskId) {
    try {
        showToast('正在启动视频生成...', 'info');

        // 调用新的视频生成 API
        const response = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({ source_id: taskId })
        });

        autoVideoTaskId = response.task_id;
        showToast('视频生成已启动，完成后将自动保存课程', 'info');

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');
    }
}

async function loadTeacherCourses() {
    const container = document.getElementById('teacherCoursesList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/teacher/courses');
        const courses = response.courses || [];

        if (courses.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[BOOK]</div>
                    <div class="empty-text">还没有生成过课程</div>
                    <button class="btn btn-primary btn-start-generate">开始生成</button>
                </div>
            `;
            // 绑定"开始生成"按钮事件
            const startBtn = container.querySelector('.btn-start-generate');
            if (startBtn) {
                startBtn.addEventListener('click', () => {
                    const generateNav = document.querySelector('[data-target="generate"]');
                    if (generateNav) generateNav.click();
                });
            }
            return;
        }

        // 使用HTML转义防止XSS
        container.innerHTML = `<div class="course-grid">${courses.map(course => {
            // 获取视频状态
            const hasVideo = course.has_video || false;
            const videoPath = course.video_path || '';
            const taskId = course.metadata?.task_id || '';
            const videoStatus = course.video_status || 'none'; // none, generating, completed, failed

            // 视频状态指示器
            let videoIndicator = '';
            if (videoStatus === 'generating') {
                videoIndicator = '<span class="video-status-badge generating" title="视频生成中">⏳ 生成中</span>';
            } else if (hasVideo) {
                videoIndicator = '<span class="video-status-badge completed" title="视频已生成">✅ 已生成</span>';
            } else {
                videoIndicator = '<span class="video-status-badge none" title="无视频">📹 无视频</span>';
            }

            // 根据视频状态生成不同的按钮组
            let videoButtons = '';
            if (videoStatus === 'generating') {
                videoButtons = `
                    <span class="video-generating-text">⏳ 生成中</span>
                `;
            } else if (hasVideo) {
                videoButtons = `
                    <button class="btn btn-success btn-play-video" data-course-id="${escapeHtmlAttr(course.id)}" data-video-path="${escapeHtmlAttr(videoPath)}" title="播放视频">
                        ▶️
                    </button>
                    <button class="btn btn-outline btn-regenerate-video" data-course-id="${escapeHtmlAttr(course.id)}" title="重新生成视频">
                        🔄
                    </button>
                `;
            } else {
                videoButtons = `
                    <button class="btn btn-primary btn-generate-video" data-course-id="${escapeHtmlAttr(course.id)}" title="生成视频">
                        🎬
                    </button>
                `;
            }

            return `
            <div class="course-card" data-course-id="${escapeHtmlAttr(course.id)}" data-video-status="${videoStatus}">
                <div class="course-card-header">
                    <div class="course-card-title">${escapeHtml(course.title || (course.grade + course.chapter))}</div>
                    <div class="course-card-meta">${escapeHtml(course.grade)} · ${escapeHtml(course.chapter)}</div>
                    ${videoIndicator}
                </div>
                <div class="course-card-body">
                    <p style="color: #666; font-size: 14px;">
                        ${course.sections && Object.keys(course.sections).length > 0 ? Object.keys(course.sections).slice(0, 3).map(k => escapeHtml(k)).join('、') : '暂无简介'}
                    </p>
                </div>
                <div class="course-card-footer">
                    <div class="course-card-actions">
                        <button class="btn btn-secondary btn-view-course" data-course-id="${escapeHtmlAttr(course.id)}">
                            预览
                        </button>
                        ${videoButtons}
                        <button class="btn btn-secondary btn-share-course" data-course-id="${escapeHtmlAttr(course.id)}">
                            📤 分享
                        </button>
                    </div>
                    <button class="btn btn-danger btn-delete-course" data-course-id="${escapeHtmlAttr(course.id)}" title="删除课程">
                        🗑️
                    </button>
                </div>
            </div>
            `;
        }).join('')}</div>`;

        // 绑定按钮事件（使用事件委托）
        container.querySelectorAll('.btn-view-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.viewCourse(courseId);
            });
        });

        // 生成视频按钮
        container.querySelectorAll('.btn-generate-video').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.generateCourseVideoFromCard(courseId);
            });
        });

        // 播放视频按钮
        container.querySelectorAll('.btn-play-video').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                const videoPath = this.dataset.videoPath;
                window.playCourseVideo(courseId, videoPath);
            });
        });

        // 重新生成视频按钮
        container.querySelectorAll('.btn-regenerate-video').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.regenerateCourseVideo(courseId);
            });
        });

        // 分享按钮
        container.querySelectorAll('.btn-share-course').forEach(btn => {
            btn.addEventListener('click', function() {
                const courseId = this.dataset.courseId;
                window.shareCourse(courseId);
            });
        });

        // 删除按钮
        container.querySelectorAll('.btn-delete-course').forEach(btn => {
            btn.addEventListener('click', async function() {
                const courseId = this.dataset.courseId;
                await deleteTeacherCourse(courseId);
            });
        });
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 删除教师课程
async function deleteTeacherCourse(courseId) {
    // 确认对话框
    if (!confirm('确定要删除这个课程吗？删除后将无法恢复！')) {
        return;
    }

    try {
        // 使用POST方式的备用接口
        await apiRequest(`/api/teacher/course/${courseId}/delete`, {
            method: 'POST'
        });
        showToast('课程已删除', 'success');
        // 刷新课程列表
        loadTeacherCourses();
    } catch (error) {
        console.error('删除课程失败:', error);
        showToast(error.message || '删除课程失败', 'error');
    }
}

async function loadStudents() {
    const container = document.getElementById('studentsList');
    const classSelect = document.getElementById('classSelect');

    if (!container) return;

    const selectedClass = classSelect ? classSelect.value : '七年级1班';

    try {
        const response = await apiRequest(`/api/teacher/students?class_name=${encodeURIComponent(selectedClass)}`);
        const students = response.students || [];

        if (students.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-text">该班级暂无学生</div>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #e5e7eb;">
                        <th style="padding: 12px; text-align: left;">姓名</th>
                        <th style="padding: 12px; text-align: left;">学号</th>
                        <th style="padding: 12px; text-align: left;">班级</th>
                    </tr>
                </thead>
                <tbody>
                    ${students.map(s => `
                        <tr style="border-bottom: 1px solid #f3f4f6;">
                            <td style="padding: 12px;">${s.username}</td>
                            <td style="padding: 12px;">${s.student_id || '-'}</td>
                            <td style="padding: 12px;">${s.class || '-'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function loadTeacherLessonPlans() {
    const container = document.getElementById('teacherLessonPlansList');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

    try {
        const response = await apiRequest('/api/teacher/lesson-plans');
        const lessonPlans = response.lesson_plans || [];

        if (lessonPlans.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[BOOK]</div>
                    <div class="empty-text">还没有保存教案</div>
                    <div class="empty-hint">生成课程后可保存为教案，方便后续查看和复用</div>
                </div>
            `;
            return;
        }

        // 按时间倒序排列
        lessonPlans.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

        container.innerHTML = lessonPlans.map(plan => `
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="flex: 1;">
                        <div style="font-weight: 600; margin-bottom: 8px;">${plan.title}</div>
                        <div style="color: #666; font-size: 14px; margin-bottom: 8px;">
                            📚 ${plan.grade || ''} ${plan.chapter || ''} | ${plan.lesson_type || '课程'}
                        </div>
                        <div style="color: #999; font-size: 12px;">
                            ${formatDate(plan.created_at)}
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" onclick="viewLessonPlan('${plan.id}')">
                            查看
                        </button>
                        <button class="btn btn-outline" onclick="downloadLessonPlan('${plan.id}')">
                            下载
                        </button>
                        <button class="btn btn-danger" onclick="deleteLessonPlan('${plan.id}')">
                            删除
                        </button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 渲染教案内容（处理 sections 字典）
function renderLessonPlanContent(plan) {
    // 优先使用 sections，若为空则尝试 content.sections
    let sections = plan.sections || {};
    if (Object.keys(sections).length === 0 && plan.content && plan.content.sections) {
        sections = plan.content.sections;
    }

    const sectionNames = Object.keys(sections);

    if (sectionNames.length === 0) {
        return `
            <div style="background: #f5f5f5; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
                <h4 style="margin: 0 0 12px 0;">课程内容</h4>
                <div style="color: #999;">暂无内容</div>
            </div>`;
    }

    let html = '<div style="margin-bottom: 20px;" class="lesson-plan-content">';
    sectionNames.forEach(name => {
        let content = sections[name];
        // 确保 content 是字符串
        if (typeof content !== 'string') {
            content = content ? JSON.stringify(content, null, 2) : '';
        }
        if (!content || !content.trim()) return;
        html += `
            <div style="background: #f5f5f5; padding: 16px; border-radius: 8px; margin-bottom: 12px;">
                <h4 style="margin: 0 0 8px 0; color: #1a73e8;">${escapeHtml(name)}</h4>
                <div style="white-space: pre-wrap; font-family: 'Microsoft YaHei', Arial, sans-serif; line-height: 1.6; color: #333; font-size: 14px;">${escapeHtml(content)}</div>
            </div>`;
    });
    html += '</div>';
    return html;
}

// 查看教案详情（复用 viewCourse 的渲染逻辑）
async function viewLessonPlan(planId) {
    try {
        const response = await apiRequest(`/api/teacher/lesson-plans/${planId}`);
        const plan = response.lesson_plan;

        // 与 viewCourse 一致：直接从 sections 获取内容
        const sections = plan.sections || {};

        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); z-index: 10000;
            display: flex; align-items: center; justify-content: center;
        `;
        modal.innerHTML = `
            <div style="background: white; border-radius: 12px; padding: 24px;
                max-width: 800px; width: 90%; max-height: 80vh; overflow-y: auto;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h3 style="margin: 0;">${escapeHtml(plan.title || '')}</h3>
                    <button onclick="this.closest('div').parentElement.remove()" style="background: none; border: none; font-size: 24px; cursor: pointer;">&times;</button>
                </div>

                <div style="margin-bottom: 20px;">
                    <strong>年级：</strong>${escapeHtml(plan.grade || '-')}
                    <span style="margin: 0 16px;"><strong>章节：</strong>${escapeHtml(plan.chapter || '-')}</span>
                    <span style="margin: 0 16px;"><strong>类型：</strong>${escapeHtml(plan.lesson_type || '-')}</span>
                </div>

                <div style="max-height: 500px; overflow-y: auto;">
                    ${Object.entries(sections).map(([key, value]) => `
                        <div style="margin-bottom: 24px;">
                            <h4 style="color: #2a78ff; margin-bottom: 12px; font-size: 16px;">${escapeHtml(key)}</h4>
                            <div style="color: #333; line-height: 1.8; white-space: pre-wrap; font-size: 14px;">${escapeHtml(value || '暂无内容')}</div>
                        </div>
                    `).join('')}
                </div>

                <div style="background: #f0f7ff; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
                    <h4 style="margin: 0 0 12px 0;">生成设置</h4>
                    <div style="font-size: 14px; color: #666;">
                        <div>内容来源：${({'lesson_plan': '教师备课教案', 'teaching_script': '课堂讲解逐字稿', 'board_design': '板书设计', 'review_outline': '复习串讲'}[plan.content_source]) || plan.content_source || '-'}</div>
                        <div>教材版本：${escapeHtml(plan.lesson_type || '-')}</div>
                        <div>生成时间：${formatDate(plan.created_at)}</div>
                    </div>
                </div>

                <div style="display: flex; gap: 12px; justify-content: flex-end;">
                    <button class="btn btn-secondary" onclick="this.closest('div').parentElement.remove()">关闭</button>
                    <button class="btn btn-primary" onclick="downloadLessonPlan('${planId}')">下载教案</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });
        // 触发 MathJax 渲染公式
        if (window.MathJax && MathJax.typesetPromise) {
            MathJax.typesetPromise([modal]).catch(err => console.warn('[MathJax] 渲染失败:', err));
        }
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 下载教案
async function downloadLessonPlan(planId) {
    try {
        const response = await apiRequest(`/api/teacher/lesson-plans/${planId}/download`);
        const plan = response.lesson_plan;

        // 获取 sections 内容
        let sections = plan.sections || {};
        if (Object.keys(sections).length === 0 && plan.content && plan.content.sections) {
            sections = plan.content.sections;
        }

        // 创建下载内容
        let content = `# ${plan.title}\n\n`;
        content += `年级：${plan.grade || ''}\n`;
        content += `章节：${plan.chapter || ''}\n`;
        content += `类型：${plan.lesson_type || ''}\n`;
        content += `生成时间：${formatDate(plan.created_at)}\n\n`;

        if (Object.keys(sections).length > 0) {
            Object.entries(sections).forEach(([name, text]) => {
                const sectionText = typeof text === 'string' ? text : JSON.stringify(text, null, 2);
                content += `## ${name}\n\n${sectionText}\n\n`;
            });
        } else {
            content += `## 课程内容\n\n无内容`;
        }

        // 创建下载链接
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${plan.title}_教案.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('教案下载成功', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 删除教案
async function deleteLessonPlan(planId) {
    if (!confirm('确定要删除这个教案吗？')) return;

    try {
        await apiRequest(`/api/teacher/lesson-plans/${planId}`, {
            method: 'DELETE'
        });
        showToast('教案已删除', 'success');
        loadTeacherLessonPlans(); // 重新加载列表
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 保存到教案管理
async function saveToLessonPlans(taskId, content) {
    try {
        showToast('正在保存到教案管理...', 'info');

        // 调用保存课程API
        const response = await apiRequest(`/course/${taskId}/save`, {
            method: 'POST'
        });

        if (response.success) {
            showToast('✅ 已保存到教案管理', 'success');

            // 关闭预览
            document.getElementById('previewSection').style.display = 'none';

            // 跳转到教案管理页面
            setTimeout(() => {
                // 触发导航到教案管理
                document.querySelectorAll('.nav-item').forEach(item => {
                    if (item.dataset.target === 'lessonPlans') {
                        item.click();
                    }
                });
            }, 1000);
        }
    } catch (error) {
        showToast('保存失败：' + error.message, 'error');
    }
}

// 格式化日期
function formatDate(dateString) {
    if (!dateString) return '-';

    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins}分钟前`;
    if (diffHours < 24) return `${diffHours}小时前`;
    if (diffDays < 7) return `${diffDays}天前`;
    return date.toLocaleDateString('zh-CN');
}

// ==================== 班级管理 ====================
function initClassForm() {
    // 初始化创建班级表单
    const createForm = document.getElementById('createClassForm');
    if (createForm && !createForm.dataset.initialized) {
        createForm.dataset.initialized = 'true';
        createForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('className').value.trim();
            const grade = document.getElementById('classGrade').value;
            const description = document.getElementById('classDesc').value.trim();

            if (!name) {
                showToast('请输入班级名称', 'error');
                return;
            }

            try {
                await apiRequest('/api/teacher/class', {
                    method: 'POST',
                    body: JSON.stringify({ name, grade, description })
                });
                showToast('班级创建成功', 'success');
                createForm.reset();
                loadClasses();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    }
}

async function loadClasses() {
    const container = document.getElementById('classList');
    if (!container) return;

    try {
        const response = await apiRequest('/api/teacher/classes');
        const classes = response.classes || [];

        if (classes.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">[GROUP]</div>
                    <div class="empty-text">还没有创建班级</div>
                </div>
            `;
            return;
        }

        container.innerHTML = classes.map(cls => `
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                    <div style="flex: 1;">
                        <h3 style="margin-bottom: 8px;">${cls.name}</h3>
                        <div style="color: #666; margin-bottom: 12px;">
                            ${cls.grade ? `<span style="margin-right: 16px;">年级: ${cls.grade}</span>` : ''}
                            <span>学生: ${cls.student_ids?.length || 0} 人</span>
                        </div>
                        ${cls.description ? `<div style="color: #999; font-size: 14px; margin-bottom: 12px;">${cls.description}</div>` : ''}
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" onclick="viewClassStudents('${cls.id}', '${cls.name}')">查看学生</button>
                        <button class="btn btn-danger" onclick="deleteClass('${cls.id}', '${cls.name}')">删除</button>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function deleteClass(classId, className) {
    if (!confirm(`确定要删除班级"${className}"吗？`)) return;

    try {
        await apiRequest(`/api/teacher/class/${classId}`, {
            method: 'DELETE'
        });
        showToast('班级已删除', 'success');
        loadClasses();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function viewClassStudents(classId, className) {
    console.log('[viewClassStudents] 开始获取学生列表', classId, className);
    try {
        const response = await apiRequest(`/api/class/${classId}/students`);
        console.log('[viewClassStudents] API响应:', response);
        const students = response.students || [];
        console.log('[viewClassStudents] 学生数量:', students.length);

        const studentList = students.length > 0
            ? students.map(s => `
                <tr>
                    <td>${s.username}</td>
                    <td>${s.student_id || '-'}</td>
                    <td>${s.email || '-'}</td>
                </tr>
            `).join('')
            : '<tr><td colspan="3" style="text-align: center; color: #999;">暂无学生</td></tr>';

        // 显示学生列表弹窗
        const modal = document.createElement('div');
        modal.className = 'modal show';  // 添加 'show' 类来显示
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 600px;">
                <div class="modal-header">
                    <h3>${className} - 学生列表</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <table>
                        <thead>
                            <tr>
                                <th>姓名</th>
                                <th>学号</th>
                                <th>邮箱</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${studentList}
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        // 显示模态框
        document.body.appendChild(modal);

        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        console.log('[viewClassStudents] 模态框已显示');
    } catch (error) {
        console.error('[viewClassStudents] 错误:', error);
        showToast(error.message, 'error');
    }
}

function showGeneratePage() {
    // 课程生成页面已包含在 HTML 中
}

// ==================== 生成课程全局变量 ====================
let currentTaskId = null;
let currentGeneratedCourseId = null; // 当前生成的课程ID

function initGenerateForm() {
    const versionSelect = document.getElementById('version');
    const gradeSelect = document.getElementById('grade');
    const chapterSelect = document.getElementById('chapter');
    const generateForm = document.getElementById('generateForm');
    const progressSection = document.getElementById('progressSection');
    const resultSection = document.getElementById('resultSection');

    // 检查generateVideo元素是否存在
    const generateVideoCheckbox = document.getElementById('generateVideo');

    // 内容源切换
    const contentSourceRadios = document.querySelectorAll('input[name="contentSource"]');
    const textbookSection = document.getElementById('textbookSection');
    const customSection = document.getElementById('customSection');

    contentSourceRadios.forEach(radio => {
        radio.addEventListener('change', (e) => {
            if (e.target.value === 'textbook') {
                textbookSection.style.display = 'block';
                customSection.style.display = 'none';
                // 重置教材选择的 required 属性
                versionSelect.required = true;
                gradeSelect.required = true;
                chapterSelect.required = true;
                document.getElementById('customTitle').required = false;
                document.getElementById('customOutline').required = false;
            } else {
                textbookSection.style.display = 'none';
                customSection.style.display = 'block';
                // 重置自定义输入的 required 属性
                versionSelect.required = false;
                gradeSelect.required = false;
                chapterSelect.required = false;
                document.getElementById('customTitle').required = true;
                document.getElementById('customOutline').required = true;
            }
        });
    });

    // 加载教材版本
    loadTextbookVersions();

    versionSelect.addEventListener('change', async () => {
        const version = versionSelect.value;
        if (!version) return;

        gradeSelect.disabled = true;
        gradeSelect.innerHTML = '<option value="">加载中...</option>';

        try {
            const response = await apiRequest(`/textbooks/${version}/grades`);
            const grades = response.grades || [];

            gradeSelect.innerHTML = '<option value="">请选择年级</option>';
            grades.forEach(grade => {
                const option = document.createElement('option');
                option.value = grade;
                option.textContent = grade;
                gradeSelect.appendChild(option);
            });
            gradeSelect.disabled = false;
        } catch (error) {
            showToast('加载年级失败', 'error');
        }
    });

    gradeSelect.addEventListener('change', async () => {
        const version = versionSelect.value;
        const grade = gradeSelect.value;
        if (!version || !grade) return;

        chapterSelect.disabled = true;
        chapterSelect.innerHTML = '<option value="">加载中...</option>';

        try {
            // 对年级参数进行URL编码，支持中文
            const encodedGrade = encodeURIComponent(grade);
            const response = await apiRequest(`/textbooks/${version}/${encodedGrade}/chapters`);
            const chapters = response.chapters || [];

            chapterSelect.innerHTML = '<option value="">请选择章节</option>';
            chapters.forEach(chapter => {
                const option = document.createElement('option');
                option.value = chapter.id;
                option.textContent = chapter.name;
                chapterSelect.appendChild(option);
            });
            chapterSelect.disabled = false;
        } catch (error) {
            showToast('加载章节失败', 'error');
        }
    });

    generateForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        // 获取选择的内容源
        const contentSource = document.querySelector('input[name="contentSource"]:checked').value;

        let requestData = {
            generate_video: false  // 总是先只生成文本，视频在预览后手动生成
        };

        // 根据内容源设置不同的参数
        if (contentSource === 'textbook') {
            // 教材章节模式：生成学生课件，固定用途为"学生自学"
            requestData.student_level = document.getElementById('studentLevel').value;
            requestData.purpose = '学生自学';
            requestData.version = versionSelect.value;
            requestData.grade = gradeSelect.value;
            requestData.chapter = chapterSelect.value;
        } else {
            // 自定义内容模式：教师专用，根据选择的类型生成
            requestData.student_level = '保持原风格';
            requestData.content_type = document.getElementById('contentType').value;

            const customTitle = document.getElementById('customTitle').value.trim();
            const customOutline = document.getElementById('customOutline').value.trim();

            if (!customTitle) {
                showToast('请输入课程标题', 'error');
                return;
            }
            if (!customOutline) {
                showToast('请输入课程大纲内容', 'error');
                return;
            }

            requestData.custom_topic = customTitle;
            requestData.custom_outline = customOutline;
            requestData.version = 'custom';
            requestData.grade = '自定义';
            requestData.chapter = 'custom';

            // 根据内容类型设置purpose
            const contentTypeToPurpose = {
                'lesson_plan': '教师备课教案',
                'teaching_script': '课堂讲解逐字稿',
                'board_design': '板书设计',
                'review_outline': '复习串讲'
            };
            requestData.purpose = contentTypeToPurpose[requestData.content_type] || '自定义内容';
        }

        // 显示进度
        progressSection.style.display = 'block';
        resultSection.style.display = 'none';
        const progressFill = document.getElementById('progressFill');
        const progressMessage = document.getElementById('progressMessage');

        try {
            // 提交生成任务
            const response = await apiRequest('/generate/course', {
                method: 'POST',
                body: JSON.stringify(requestData)
            });

            currentTaskId = response.task_id;

            // 轮询进度
            pollProgress();

        } catch (error) {
            showToast(error.message, 'error');
            progressSection.style.display = 'none';
        }
    });

    async function pollProgress() {
        if (!currentTaskId) return;

        try {
            const response = await apiRequest(`/progress/${currentTaskId}`);
            // 后端返回的是 percent 而不是 progress
            const progress = response.percent || 0;
            const message = response.message || '处理中...';

            progressFill.style.width = `${progress}%`;
            progressMessage.textContent = message;

            // 更新百分比显示
            const progressPercent = document.getElementById('progressPercent');
            if (progressPercent) {
                progressPercent.textContent = `${Math.round(progress)}%`;
            }

            if (response.status === 'completed') {
                // 完成 - 显示预览界面
                progressSection.style.display = 'none';
                await showPreviewSection(currentTaskId);

                // 显示带操作按钮的成功提示
                showToast('课程生成成功！', 'success', {
                    actions: [
                        { text: '继续编辑', onClick: () => scrollToPreview() },
                        { text: '生成视频', primary: true, onClick: () => startVideoGenerationFromPreview(currentTaskId) }
                    ]
                });
            } else if (response.status === 'failed') {
                // 失败
                progressSection.style.display = 'none';
                showToast(`生成失败：${response.error || '未知错误'}`, 'error');
            } else {
                // 继续轮询（缩短间隔以更及时显示进度）
                setTimeout(pollProgress, 500);
            }
        } catch (error) {
            showToast('获取进度失败', 'error');
        }
    }

    window.exportResult = async function(format) {
        if (!currentTaskId) {
            showToast('没有可导出的课程', 'error');
            return;
        }

        window.open(`${API_BASE}/export/${format}/${currentTaskId}?session_id=${state.sessionId}`, '_blank');
    };
}

// ==================== 全局函数 ====================

// 预览课程内容
async function showPreviewSection(taskId) {
    try {
        const response = await apiRequest(`/course/${taskId}/preview`);
        const { content, validation } = response;

        const previewSection = document.getElementById('previewSection');
        const previewContent = document.getElementById('previewContent');
        const validationResult = document.getElementById('validationResult');
        const validationStatus = document.getElementById('validationStatus');

        // 显示验证状态
        if (validation) {
            if (validation.is_valid && !validation.has_warnings) {
                validationStatus.innerHTML = '✓ 校验通过';
                validationStatus.style.background = '#d1fae5';
                validationStatus.style.color = '#065f46';
            } else if (validation.is_valid && validation.has_warnings) {
                validationStatus.innerHTML = `⚠ 通过（${validation.warnings?.length || 0}个警告）`;
                validationStatus.style.background = '#fef3c7';
                validationStatus.style.color = '#92400e';
            } else {
                validationStatus.innerHTML = `✗ 校验失败（${validation.errors?.length || 0}个错误）`;
                validationStatus.style.background = '#fee2e2';
                validationStatus.style.color = '#991b1b';
            }

            // 显示验证详情
            if (validation.errors && validation.errors.length > 0) {
                validationResult.innerHTML = `
                    <div style="background: #fee2e2; color: #991b1b; padding: 12px; border-radius: 8px; margin-bottom: 12px;">
                        <strong>错误：</strong>
                        <ul style="margin: 8px 0 0 20px;">
                            ${validation.errors.map(e => `<li>${e}</li>`).join('')}
                        </ul>
                    </div>
                `;
            } else if (validation.warnings && validation.warnings.length > 0) {
                validationResult.innerHTML = `
                    <div style="background: #fef3c7; color: #92400e; padding: 12px; border-radius: 8px; margin-bottom: 12px;">
                        <strong>警告：</strong>
                        <ul style="margin: 8px 0 0 20px;">
                            ${validation.warnings.map(w => `<li>${w}</li>`).join('')}
                        </ul>
                    </div>
                `;
            } else {
                validationResult.innerHTML = '';
            }
        }

        // 显示内容预览（使用 smartFormat 渲染格式化内容）
        previewContent.innerHTML = `
            <h4 style="margin-bottom: 12px;">${escapeHtml(content.title || '课程标题')}</h4>
            ${Object.entries(content.sections || {}).map(([key, value]) => `
                <div style="margin-bottom: 16px; padding: 12px; background: #f8f9fa; border-radius: 8px;">
                    <h5 style="color: #2a78ff; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #e9ecef;">${escapeHtml(key)}</h5>
                    <div style="color: #333; line-height: 1.8;">${smartFormat(value || '')}</div>
                </div>
            `).join('')}
        `;

        // 绑定按钮事件（新流程：先显示文本预览按钮）
        bindPreviewButtonsTextGenerated(taskId, content);

        previewSection.style.display = 'block';

        // 渲染数学公式
        if (window.MathJax) {
            MathJax.typesetPromise([previewContent]).catch((err) => console.log('[MathJax] 渲染错误:', err));
        }
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// ==================== 新流程：文本生成后的按钮绑定 ====================
function bindPreviewButtonsTextGenerated(taskId, content) {
    const videoNotice = document.getElementById('videoNotice');
    const actionButtonsText = document.getElementById('actionButtonsText');
    const actionButtonsVideo = document.getElementById('actionButtonsVideo');

    // 隐藏视频生成提示，显示文本生成后的按钮
    if (videoNotice) {
        videoNotice.style.display = 'none';
    }
    if (actionButtonsText) {
        actionButtonsText.style.display = 'flex';
    }
    if (actionButtonsVideo) {
        actionButtonsVideo.style.display = 'none';
    }

    // 检查是否是教师自定义内容
    const isCustomContent = content.metadata &&
        content.metadata.content_type &&
        ['lesson_plan', 'teaching_script', 'board_design', 'review_outline'].includes(content.metadata.content_type);

    // 生成视频按钮 / 保存到教案管理按钮
    const generateVideoBtn = document.getElementById('generateVideoBtn');
    if (generateVideoBtn) {
        // 移除旧的事件监听器（如果有）
        const oldGenerateHandler = generateVideoBtn._generateHandler;
        if (oldGenerateHandler) {
            generateVideoBtn.removeEventListener('click', oldGenerateHandler);
        }

        if (isCustomContent) {
            // 教师自定义内容：显示"保存到教案管理"按钮
            generateVideoBtn.textContent = '💾 保存到教案管理';
            generateVideoBtn.className = 'btn btn-success';

            const saveToLessonPlanHandler = () => {
                saveToLessonPlans(taskId, content);
            };

            generateVideoBtn._generateHandler = saveToLessonPlanHandler;
            generateVideoBtn.addEventListener('click', saveToLessonPlanHandler);
        } else {
            // 学生课程：显示"生成讲解视频"按钮
            generateVideoBtn.textContent = '🎬 生成讲解视频';
            generateVideoBtn.className = 'btn btn-primary';

            const generateHandler = () => {
                startVideoGenerationFromPreview(taskId);
            };

            generateVideoBtn._generateHandler = generateHandler;
            generateVideoBtn.addEventListener('click', generateHandler);
        }
    }

    // 编辑内容按钮
    const editBtn = document.getElementById('editCourseBtn');
    if (editBtn) {
        // 移除旧的事件监听器（如果有）
        const oldEditHandler = editBtn._editHandler;
        if (oldEditHandler) {
            editBtn.removeEventListener('click', oldEditHandler);
        }

        const editHandler = () => {
            showEditSection(content, taskId);
        };

        editBtn._editHandler = editHandler;
        editBtn.addEventListener('click', editHandler);
    }

    // 重新生成按钮
    const regenerateBtn = document.getElementById('regenerateBtn');
    if (regenerateBtn) {
        // 移除旧的事件监听器（如果有）
        const oldRegenerateHandler = regenerateBtn._regenerateHandler;
        if (oldRegenerateHandler) {
            regenerateBtn.removeEventListener('click', oldRegenerateHandler);
        }

        const regenerateHandler = () => {
            document.getElementById('previewSection').style.display = 'none';
            document.getElementById('generateForm').reset();
            document.querySelector('input[name="contentSource"][value="textbook"]').checked = true;
            document.getElementById('textbookSection').style.display = 'block';
            document.getElementById('customSection').style.display = 'none';
            showToast('请重新填写生成参数', 'info');
        };

        regenerateBtn._regenerateHandler = regenerateHandler;
        regenerateBtn.addEventListener('click', regenerateHandler);
    }

    // 取消按钮
    const cancelBtn = document.getElementById('cancelPreviewBtn');
    if (cancelBtn) {
        // 移除旧的事件监听器（如果有）
        const oldCancelHandler = cancelBtn._cancelHandler2;
        if (oldCancelHandler) {
            cancelBtn.removeEventListener('click', oldCancelHandler);
        }

        const cancelHandler = () => {
            document.getElementById('previewSection').style.display = 'none';
        };

        cancelBtn._cancelHandler2 = cancelHandler;
        cancelBtn.addEventListener('click', cancelHandler);
    }
}

// ==================== 新流程：视频生成后的按钮绑定 ====================
function bindPreviewButtonsVideoGenerated(taskId, content) {
    const videoNotice = document.getElementById('videoNotice');
    const actionButtonsText = document.getElementById('actionButtonsText');
    const actionButtonsVideo = document.getElementById('actionButtonsVideo');

    // 显示视频生成完成提示，切换到视频生成后的按钮
    if (videoNotice) {
        videoNotice.style.display = 'block';
        videoNotice.innerHTML = `
            <div style="background: #d1fae5; color: #065f46; padding: 16px; border-radius: 8px; margin-bottom: 16px; text-align: center;">
                <strong>✅ 视频生成完成！</strong><br>
                <span style="font-size: 14px;">点击"保存到我的课程"按钮完成课程保存</span>
            </div>
        `;
    }
    if (actionButtonsText) {
        actionButtonsText.style.display = 'none';
    }
    if (actionButtonsVideo) {
        actionButtonsVideo.style.display = 'flex';
    }

    // 保存到我的课程按钮
    const saveBtn = document.getElementById('saveCourseBtn');
    if (saveBtn) {
        // 移除旧的事件监听器（如果有），避免重复绑定导致多次调用
        const oldHandler = saveBtn._saveHandler;
        if (oldHandler) {
            saveBtn.removeEventListener('click', oldHandler);
        }

        // 创建新的处理函数
        const saveHandler = async () => {
            try {
                // 禁用按钮防止重复点击
                saveBtn.disabled = true;
                saveBtn.textContent = '保存中...';

                const response = await apiRequest(`/course/${taskId}/save`, {
                    method: 'POST'
                });
                const courseId = response.course_id;
                currentGeneratedCourseId = courseId;

                showToast('课程已保存到我的课程！', 'success', {
                    actions: [
                        { text: '查看我的课程', primary: true, onClick: () => {
                            // 切换到"我的课程"标签页
                            const coursesNav = document.querySelector('[data-target="courses"]');
                            if (coursesNav) {
                                coursesNav.click();
                            }
                        }},
                        { text: '继续生成', onClick: () => {
                            // 切换到"生成课程"标签页
                            const generateNav = document.querySelector('[data-target="generate"]');
                            if (generateNav) {
                                generateNav.click();
                            }
                        }}
                    ]
                });
                document.getElementById('previewSection').style.display = 'none';

                loadTeacherCourses(); // 刷新课程列表
            } catch (error) {
                showToast(error.message, 'error');
            } finally {
                // 恢复按钮状态
                saveBtn.disabled = false;
                saveBtn.textContent = '💾 保存到我的课程';
            }
        };

        // 保存处理函数引用以便后续移除
        saveBtn._saveHandler = saveHandler;
        saveBtn.addEventListener('click', saveHandler);
    }

    // 编辑内容按钮（视频生成后）
    const editAfterVideoBtn = document.getElementById('editCourseAfterVideoBtn');
    if (editAfterVideoBtn) {
        // 移除旧的事件监听器（如果有）
        const oldEditHandler = editAfterVideoBtn._editHandler;
        if (oldEditHandler) {
            editAfterVideoBtn.removeEventListener('click', oldEditHandler);
        }

        const editHandler = () => {
            showEditSection(content, taskId);
        };

        editAfterVideoBtn._editHandler = editHandler;
        editAfterVideoBtn.addEventListener('click', editHandler);
    }

    // 取消按钮
    const cancelBtn = document.getElementById('cancelPreviewAfterVideoBtn');
    if (cancelBtn) {
        // 移除旧的事件监听器（如果有）
        const oldCancelHandler = cancelBtn._cancelHandler;
        if (oldCancelHandler) {
            cancelBtn.removeEventListener('click', oldCancelHandler);
        }

        const cancelHandler = () => {
            document.getElementById('previewSection').style.display = 'none';
        };

        cancelBtn._cancelHandler = cancelHandler;
        cancelBtn.addEventListener('click', cancelHandler);
    }
}

// ==================== 从预览界面启动视频生成 ====================
async function startVideoGenerationFromPreview(taskId) {
    try {
        const videoNotice = document.getElementById('videoNotice');
        const actionButtonsText = document.getElementById('actionButtonsText');

        // 显示视频生成进度提示
        if (videoNotice) {
            videoNotice.style.display = 'block';
            videoNotice.innerHTML = `
                <div style="background: #e0f2fe; color: #0369a1; padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                    <div style="display: flex; align-items: center; justify-content: center; gap: 12px;">
                        <div class="spinner" style="width: 20px; height: 20px; border-width: 2px;"></div>
                        <div>
                            <strong>🎬 正在生成视频...</strong><br>
                            <span style="font-size: 13px;">视频生成过程中请勿关闭页面，完成后将显示保存按钮</span>
                        </div>
                    </div>
                    <div style="margin-top: 12px;">
                        <div class="progress-bar">
                            <div class="progress-fill" id="videoProgressFill" style="width: 0%;"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
                            <span id="videoProgressMessage" style="font-size: 13px;">准备中...</span>
                            <span id="videoProgressPercent" style="font-size: 13px; font-weight: 600;">0%</span>
                        </div>
                    </div>
                </div>
            `;
        }

        // 隐藏按钮防止重复点击
        if (actionButtonsText) {
            actionButtonsText.style.display = 'none';
        }

        // 启动视频生成
        const response = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({ source_id: taskId })
        });

        const videoTaskId = response.task_id;

        // 轮询视频生成进度
        pollVideoProgress(videoTaskId, taskId);

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');

        // 恢复按钮显示
        const actionButtonsText = document.getElementById('actionButtonsText');
        if (actionButtonsText) {
            actionButtonsText.style.display = 'flex';
        }

        const videoNotice = document.getElementById('videoNotice');
        if (videoNotice) {
            videoNotice.style.display = 'none';
        }
    }
}

// ==================== 轮询视频生成进度 ====================
async function pollVideoProgress(videoTaskId, courseTaskId) {
    try {
        const response = await apiRequest(`/progress/${videoTaskId}`);
        // 后端返回的是 percent 而不是 progress
        const progress = response.percent || 0;
        const message = response.message || '处理中...';

        // 更新进度条
        const progressFill = document.getElementById('videoProgressFill');
        const progressMessage = document.getElementById('videoProgressMessage');
        const progressPercent = document.getElementById('videoProgressPercent');

        if (progressFill) {
            progressFill.style.width = `${progress}%`;
        }
        if (progressMessage) {
            progressMessage.textContent = message;
        }
        if (progressPercent) {
            progressPercent.textContent = `${Math.round(progress)}%`;
        }

        if (response.status === 'completed') {
            // 视频生成完成，重新加载预览并切换到视频生成后的按钮
            showToast('视频生成完成！', 'success');
            await showPreviewSection(courseTaskId);
            // 切换到视频生成后的按钮状态
            const previewResponse = await apiRequest(`/course/${courseTaskId}/preview`);
            bindPreviewButtonsVideoGenerated(courseTaskId, previewResponse.content);
        } else if (response.status === 'failed') {
            showToast('视频生成失败: ' + (response.error || '未知错误'), 'error');

            // 恢复按钮显示
            const actionButtonsText = document.getElementById('actionButtonsText');
            if (actionButtonsText) {
                actionButtonsText.style.display = 'flex';
            }

            const videoNotice = document.getElementById('videoNotice');
            if (videoNotice) {
                videoNotice.innerHTML = `
                    <div style="background: #fee2e2; color: #991b1b; padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                        <strong>❌ 视频生成失败</strong><br>
                        <span style="font-size: 14px;">${response.error || '未知错误，请重试'}</span>
                    </div>
                `;
            }
        } else {
            // 继续轮询
            setTimeout(() => pollVideoProgress(videoTaskId, courseTaskId), 500);
        }
    } catch (error) {
        console.error('获取视频进度失败:', error);
        showToast('获取视频进度失败', 'error');

        // 恢复按钮显示
        const actionButtonsText = document.getElementById('actionButtonsText');
        if (actionButtonsText) {
            actionButtonsText.style.display = 'flex';
        }

        const videoNotice = document.getElementById('videoNotice');
        if (videoNotice) {
            videoNotice.style.display = 'none';
        }
    }
}

// 生成有效的HTML ID
function generateValidId(prefix, key) {
    // 将key转换为有效的HTML ID：移除特殊字符，用下划线替换
    const sanitized = key.replace(/[^a-zA-Z0-9_-]/g, '_');
    return `${prefix}_${sanitized}`;
}

// 显示编辑界面
async function showEditSection(content, taskId) {
    const editSection = document.getElementById('editSection');
    const editForm = document.getElementById('editForm');
    const previewSection = document.getElementById('previewSection');
    const videoWarning = document.getElementById('editVideoWarning');

    previewSection.style.display = 'none';

    // 检查是否已生成视频
    let hasVideo = false;
    try {
        const previewResponse = await apiRequest(`/course/${taskId}/preview`);
        hasVideo = previewResponse.has_video || false;
    } catch (error) {
        console.error('检查视频状态失败:', error);
    }

    // 显示/隐藏视频警告横幅
    if (videoWarning) {
        videoWarning.style.display = hasVideo ? 'block' : 'none';
    }

    // 如果已生成视频，额外显示toast警告提示
    if (hasVideo) {
        showToast('⚠️ 注意：编辑后视频内容与文字内容可能不一致，建议重新生成视频', 'warning', {
            actions: [
                { text: '继续编辑', onClick: () => {} },
                { text: '取消', primary: true, onClick: () => {
                    editSection.style.display = 'none';
                    previewSection.style.display = 'block';
                }}
            ],
            duration: 6000
        });
    }

    // 创建key到ID的映射
    const keyToIdMap = {};
    Object.keys(content.sections || {}).forEach(key => {
        keyToIdMap[key] = generateValidId('edit', key);
    });

    // 使用HTML转义防止XSS，编辑表单需要转义属性值
    editForm.innerHTML = `
        <div class="form-group">
            <label for="editTitle">课程标题</label>
            <input type="text" id="editTitle" class="form-control" value="${escapeHtmlAttr(content.title || '')}">
        </div>
        ${Object.entries(content.sections || {}).map(([key, value]) => {
            const validId = keyToIdMap[key];
            return `
            <div class="form-group" style="margin-top: 16px;">
                <label for="${validId}">${escapeHtml(key)}</label>
                <textarea id="${validId}" class="form-control" rows="6">${escapeHtml(value || '')}</textarea>
            </div>
            `;
        }).join('')}
    `;

    // 绑定编辑按钮事件
    const saveEditBtn = document.getElementById('saveEditBtn');
    const cancelEditBtn = document.getElementById('cancelEditBtn');

    saveEditBtn.onclick = async () => {
        // 保存编辑后的内容
        const editedContent = {
            title: document.getElementById('editTitle').value,
            sections: {}
        };

        Object.keys(content.sections || {}).forEach(key => {
            const validId = keyToIdMap[key];
            const element = document.getElementById(validId);
            if (element) {
                editedContent.sections[key] = element.value;
            } else {
                console.warn(`Element not found for key: ${key}, id: ${validId}`);
            }
        });

        // 保存编辑到后端
        try {
            await apiRequest(`/course/${taskId}/update`, {
                method: 'POST',
                body: JSON.stringify(editedContent)
            });

            editSection.style.display = 'none';

            // 重新加载预览，保持当前状态（文本或视频已生成）
            await showPreviewSection(taskId);

            // 检查视频是否已生成，决定显示哪种按钮
            const previewResponse = await apiRequest(`/course/${taskId}/preview`);
            if (previewResponse.has_video) {
                bindPreviewButtonsVideoGenerated(taskId, previewResponse.content);
                // 视频已生成，提示内容不一致
                showToast('修改已保存！视频内容与文字内容可能不一致', 'warning', {
                    actions: [
                        { text: '重新生成视频', primary: true, onClick: () => startVideoGenerationFromPreview(taskId) },
                        { text: '稍后处理', onClick: () => {} }
                    ]
                });
            } else {
                bindPreviewButtonsTextGenerated(taskId, previewResponse.content);
                showToast('修改已保存', 'success');
            }
        } catch (error) {
            showToast('保存修改失败: ' + error.message, 'error');
        }
    };

    cancelEditBtn.onclick = () => {
        editSection.style.display = 'none';
        previewSection.style.display = 'block';
    };

    editSection.style.display = 'block';
}

// 使用编辑后的内容显示预览
function showPreviewSectionWithContent(content) {
    document.getElementById('editSection').style.display = 'none';

    const previewSection = document.getElementById('previewSection');
    const previewContent = document.getElementById('previewContent');

    // 使用 smartFormat 渲染格式化内容
    previewContent.innerHTML = `
        <h4 style="margin-bottom: 12px;">${escapeHtml(content.title || '课程标题')}</h4>
        ${Object.entries(content.sections || {}).map(([key, value]) => `
            <div style="margin-bottom: 16px; padding: 12px; background: #f8f9fa; border-radius: 8px;">
                <h5 style="color: #2a78ff; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #e9ecef;">${escapeHtml(key)}</h5>
                <div style="color: #333; line-height: 1.8;">${smartFormat(value || '')}</div>
            </div>
        `).join('')}
    `;

    previewSection.style.display = 'block';

    // 渲染数学公式
    if (window.MathJax) {
        MathJax.typesetPromise([previewContent]).catch((err) => console.log('[MathJax] 渲染错误:', err));
    }
}

// 版本对比功能
async function showVersionCompare(courseId) {
    try {
        const response = await apiRequest(`/course/${courseId}/versions`);
        const versions = response.versions || [];

        if (versions.length < 2) {
            showToast('需要至少两个版本才能对比', 'error');
            return;
        }

        // 显示版本选择界面
        const compareSection = document.getElementById('compareSection');
        const compareContent = document.getElementById('compareContent');

        // 使用HTML转义防止XSS
        compareContent.innerHTML = `
            <div class="form-group">
                <label>选择版本1</label>
                <select id="version1Select" class="form-control form-select">
                    ${versions.map(v => `
                        <option value="${escapeHtmlAttr(v.id)}">版本 ${escapeHtml(v.version_number)} (${new Date(v.created_at).toLocaleString()})</option>
                    `).join('')}
                </select>
            </div>
            <div class="form-group" style="margin-top: 12px;">
                <label>选择版本2</label>
                <select id="version2Select" class="form-control form-select">
                    ${versions.map((v, i) => `
                        <option value="${escapeHtmlAttr(v.id)}" ${i === versions.length - 2 ? 'selected' : ''}>版本 ${escapeHtml(v.version_number)} (${new Date(v.created_at).toLocaleString()})</option>
                    `).join('')}
                </select>
            </div>
            <button class="btn btn-primary" id="doCompareBtn" style="margin-top: 16px;">开始对比</button>
            <div id="compareResult" style="margin-top: 20px;"></div>
        `;

        // 绑定对比按钮事件
        document.getElementById('doCompareBtn').onclick = async () => {
            const version1 = document.getElementById('version1Select').value;
            const version2 = document.getElementById('version2Select').value;

            if (version1 === version2) {
                showToast('请选择不同的版本进行对比', 'error');
                return;
            }

            const compareResponse = await apiRequest(`/course/version/${version1}/compare/${version2}`);
            const comparison = compareResponse.comparison;

            // 使用HTML转义防止XSS
            document.getElementById('compareResult').innerHTML = `
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 16px;">
                    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #fafafa;">
                        <h4 style="color: #2a78ff; margin-bottom: 12px;">版本 ${escapeHtml(comparison.version1.number)}</h4>
                        <div><strong>标题：</strong>${escapeHtml(comparison.version1.title)}</div>
                        <div><strong>章节数：</strong>${escapeHtml(comparison.version1.sections_count)}</div>
                        <div><strong>创建时间：</strong>${new Date(comparison.version1.created_at).toLocaleString()}</div>
                        <div style="margin-top: 12px; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">${escapeHtml(comparison.version1.content?.substring?.(0, 500) || '无内容预览')}</div>
                    </div>
                    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #fafafa;">
                        <h4 style="color: #7a41ff; margin-bottom: 12px;">版本 ${escapeHtml(comparison.version2.number)}</h4>
                        <div><strong>标题：</strong>${escapeHtml(comparison.version2.title)}</div>
                        <div><strong>章节数：</strong>${escapeHtml(comparison.version2.sections_count)}</div>
                        <div><strong>创建时间：</strong>${new Date(comparison.version2.created_at).toLocaleString()}</div>
                        <div style="margin-top: 12px; white-space: pre-wrap; max-height: 300px; overflow-y: auto;">${escapeHtml(comparison.version2.content?.substring?.(0, 500) || '无内容预览')}</div>
                    </div>
                </div>
            `;
        };

        // 绑定关闭按钮事件
        document.getElementById('cancelCompareBtn').onclick = () => {
            compareSection.style.display = 'none';
        };

        compareSection.style.display = 'block';
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// 查看课程详情（教师端预览功能）
window.viewCourse = async function(courseId) {
    console.log('[viewCourse] Called with courseId:', courseId);
    try {
        console.log('[viewCourse] Fetching courses...');
        const response = await apiRequest(`/api/teacher/courses`);
        console.log('[viewCourse] Response:', response);
        const course = response.courses?.find(c => c.id === courseId);
        console.log('[viewCourse] Found course:', course);

        if (!course) {
            console.error('[viewCourse] Course not found!');
            showToast('课程不存在', 'error');
            return;
        }

        // 直接从 course.sections 获取章节内容
        const sections = course.sections || {};
        console.log('[viewCourse] Course sections:', Object.keys(sections));

        // 创建预览弹窗
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.cssText = 'display: flex !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0,0,0,0.5) !important; z-index: 10000 !important; align-items: center !important; justify-content: center !important;';
        console.log('[viewCourse] Creating modal...');
        // 使用HTML转义防止XSS
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 800px; max-height: 80vh; overflow-y: auto;">
                <div class="modal-header">
                    <h3>${escapeHtml(course.title || '课程详情')}</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div style="margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb;">
                        <div style="color: #666; font-size: 14px; margin-bottom: 8px;">
                            <span style="margin-right: 16px;">📚 ${escapeHtml(course.grade || '')}</span>
                            <span>📖 ${escapeHtml(course.chapter || '')}</span>
                        </div>
                        <div style="color: #999; font-size: 13px;">
                            创建时间: ${course.created_at ? new Date(course.created_at).toLocaleString('zh-CN') : '未知'}
                        </div>
                    </div>
                    <div style="max-height: 500px; overflow-y: auto;">
                        ${Object.entries(sections).map(([key, value]) => `
                            <div style="margin-bottom: 24px;">
                                <h4 style="color: #2a78ff; margin-bottom: 12px; font-size: 16px;">${escapeHtml(key)}</h4>
                                <div style="color: #333; line-height: 1.8; white-space: pre-wrap; font-size: 14px;">${escapeHtml(value || '暂无内容')}</div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">关闭</button>
                    <button class="btn btn-primary" onclick="shareCourse('${escapeHtmlAttr(courseId)}')">分享到班级</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        console.log('[viewCourse] Modal appended to body');

        // 点击背景关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        // 触发 MathJax 渲染公式
        if (window.MathJax && MathJax.typesetPromise) {
            MathJax.typesetPromise([modal]).catch(err => console.warn('[MathJax] 渲染失败:', err));
        }

    } catch (error) {
        console.error('[viewCourse] Error:', error);
        showToast('加载课程详情失败: ' + error.message, 'error');
    }
};

// 从课程卡片直接生成视频
window.generateCourseVideoFromCard = async function(courseId) {
    try {
        // 获取课程详情
        const response = await apiRequest('/api/teacher/courses');
        const course = response.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 构建课程内容
        let content = '';
        if (course.content) {
            if (course.content.sections) {
                const sections = course.content.sections;
                content = Object.entries(sections).map(([key, value]) =>
                    `${key}\n${value}`
                ).join('\n\n');
            } else if (course.content.full_text) {
                content = course.content.full_text;
            }
        }

        if (!content) {
            content = `课程标题: ${course.title}\n年级: ${course.grade}\n章节: ${course.chapter}`;
        }

        // 确认生成
        if (!confirm(`确定要为课程"${course.title}"生成讲解视频吗？`)) {
            return;
        }

        const videoResponse = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: course.id,
                title: course.title,
                content: content
            })
        });

        const taskId = videoResponse.task_id;
        showToast('视频生成任务已启动，完成后将自动更新课程', 'success');

    } catch (error) {
        console.error('启动视频生成失败:', error);
        showToast('启动视频生成失败: ' + error.message, 'error');
    }
};

// 播放课程视频
window.playCourseVideo = async function(courseId, videoPath) {
    try {
        // 获取课程详情
        const response = await apiRequest('/api/teacher/courses');
        const course = response.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 创建视频播放模态框
        const modal = document.createElement('div');
        modal.className = 'modal video-modal';
        modal.style.cssText = 'display: flex !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0,0,0,0.8) !important; z-index: 10000 !important; align-items: center !important; justify-content: center !important;';

        // 使用API端点获取视频流（添加session_id参数进行认证）
        const videoApiUrl = `/api/video/course/${courseId}?session_id=${state.sessionId}`;

        modal.innerHTML = `
            <div class="modal-content video-modal-content" style="max-width: 1200px; width: 95%; max-height: 90vh; background: #000; border-radius: 12px; overflow: hidden; display: flex; flex-direction: column;">
                <div class="modal-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; padding: 16px 20px; flex-shrink: 0;">
                    <h3 style="color: white; margin: 0; font-size: 18px;">${escapeHtml(course.title || '课程')} - 讲解视频</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove(); if(document.getElementById('courseVideoPlayer')) document.getElementById('courseVideoPlayer').pause();" style="color: white; font-size: 28px; background: none; border: none; cursor: pointer; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; border-radius: 50%; transition: background 0.2s;" onmouseover="this.style.background='rgba(255,255,255,0.2)'" onmouseout="this.style.background='none'">&times;</button>
                </div>
                <div class="modal-body" style="padding: 0; background: #000; flex: 1; display: flex; align-items: center; justify-content: center; min-height: 400px;">
                    <div id="videoLoading" style="color: white; display: flex; flex-direction: column; align-items: center; gap: 16px;">
                        <div class="spinner" style="border: 3px solid rgba(255,255,255,0.3); border-top-color: white; width: 48px; height: 48px; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                        <div>加载视频中...</div>
                    </div>
                    <video id="courseVideoPlayer" controls style="width: 100%; height: 100%; max-height: calc(90vh - 80px); background: #000; display: none;"
                           onloadeddata="document.getElementById('videoLoading').style.display='none'; this.style.display='block';"
                           onerror="document.getElementById('videoLoading').innerHTML='<div style=\\'padding: 40px; text-align: center;\\'><div style=\\'font-size: 48px; margin-bottom: 16px;\\'>⚠️</div><div>视频加载失败</div><div style=\\'font-size: 13px; color: #999; margin-top: 12px;\\'>请检查视频文件是否存在或联系管理员</div><button class=\\'btn btn-secondary\\' onclick=\\'location.reload()\\' style=\\'margin-top: 16px;\\'>刷新页面</button></div>'">
                        <source src="${escapeHtmlAttr(videoApiUrl)}" type="video/mp4">
                        您的浏览器不支持视频播放。
                    </video>
                </div>
            </div>
            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;

        document.body.appendChild(modal);

        // 点击背景关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                const video = document.getElementById('courseVideoPlayer');
                if (video) video.pause();
                modal.remove();
            }
        });

        // ESC键关闭
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                const video = document.getElementById('courseVideoPlayer');
                if (video) video.pause();
                modal.remove();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        // 模态框关闭时清理
        modal.addEventListener('remove', () => {
            document.removeEventListener('keydown', escHandler);
        });

    } catch (error) {
        console.error('播放视频失败:', error);
        showToast('播放视频失败: ' + error.message, 'error');
    }
};

// 重新生成课程视频
window.regenerateCourseVideo = async function(courseId) {
    try {
        // 获取课程详情
        const response = await apiRequest('/api/teacher/courses');
        const course = response.courses?.find(c => c.id === courseId);

        if (!course) {
            showToast('无法找到课程信息', 'error');
            return;
        }

        // 确认重新生成
        const confirmMsg = `该课程已存在视频，确定要重新生成吗？\n\n⚠️ 注意：\n- 旧视频将被覆盖\n- 生成过程可能需要几分钟\n- 生成期间不能关闭页面`;
        if (!confirm(confirmMsg)) {
            return;
        }

        // 更新课程卡片状态为"生成中"
        const courseCard = document.querySelector(`.course-card[data-course-id="${courseId}"]`);
        if (courseCard) {
            courseCard.dataset.videoStatus = 'generating';
            // 重新加载课程列表以更新UI
            setTimeout(() => loadTeacherCourses(), 500);
        }

        // 构建课程内容
        let content = '';
        if (course.content) {
            if (course.content.sections) {
                const sections = course.content.sections;
                content = Object.entries(sections).map(([key, value]) =>
                    `${key}\n${value}`
                ).join('\n\n');
            } else if (course.content.full_text) {
                content = course.content.full_text;
            }
        }

        if (!content) {
            content = `课程标题: ${course.title}\n年级: ${course.grade}\n章节: ${course.chapter}`;
        }

        // 启动视频生成
        const videoResponse = await apiRequest('/api/video/generate', {
            method: 'POST',
            body: JSON.stringify({
                course_id: course.id,
                title: course.title,
                content: content,
                regenerate: true  // 标记为重新生成
            })
        });

        const taskId = videoResponse.task_id;
        showToast('视频重新生成任务已启动，完成后将自动更新课程', 'success');

        // 开始轮询视频生成状态
        startVideoGenerationPolling(courseId, taskId);

    } catch (error) {
        console.error('重新生成视频失败:', error);
        showToast('重新生成视频失败: ' + error.message, 'error');
        // 失败时恢复状态
        const courseCard = document.querySelector(`.course-card[data-course-id="${courseId}"]`);
        if (courseCard) {
            courseCard.dataset.videoStatus = 'completed';
            loadTeacherCourses();
        }
    }
};

// 轮询视频生成状态
function startVideoGenerationPolling(courseId, taskId) {
    const pollInterval = setInterval(async () => {
        try {
            const response = await apiRequest(`/api/task/${taskId}/status`);

            if (response.status === 'completed' || response.status === 'failed') {
                clearInterval(pollInterval);

                if (response.status === 'completed') {
                    showToast('视频生成完成！', 'success');
                } else {
                    showToast('视频生成失败，请重试', 'error');
                }

                // 刷新课程列表
                loadTeacherCourses();
            }
        } catch (error) {
            console.error('轮询视频状态失败:', error);
            clearInterval(pollInterval);
        }
    }, 3000);  // 每3秒轮询一次

    // 10分钟后停止轮询
    setTimeout(() => {
        clearInterval(pollInterval);
    }, 600000);
}

window.shareCourse = async function(courseId) {
    console.log('[shareCourse] Called with courseId:', courseId);
    // 分享课程到班级
    try {
        console.log('[shareCourse] Fetching classes...');
        // 获取教师的班级列表
        const response = await apiRequest('/api/teacher/classes');
        console.log('[shareCourse] Classes response:', response);
        const classes = response.classes || [];

        if (classes.length === 0) {
            console.error('[shareCourse] No classes found!');
            showToast('请先创建班级', 'error');
            return;
        }

        console.log('[shareCourse] Found classes:', classes.length);

        // 创建分享对话框
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.cssText = 'display: flex !important; position: fixed !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; background: rgba(0,0,0,0.5) !important; z-index: 10000 !important; align-items: center !important; justify-content: center !important;';
        console.log('[shareCourse] Creating modal...');
        // 使用HTML转义防止XSS
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 500px;">
                <div class="modal-header">
                    <h3>分享课程到班级</h3>
                    <button class="modal-close" onclick="this.closest('.modal').remove()">&times;</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label for="shareClassSelect">选择班级</label>
                        <select id="shareClassSelect" class="form-control form-select">
                            ${classes.map(cls =>
                                `<option value="${escapeHtmlAttr(cls.id)}">${escapeHtml(cls.name)} (${escapeHtml(String(cls.student_ids?.length || 0))}人)</option>`
                            ).join('')}
                        </select>
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
                    <button class="btn btn-primary" id="confirmShareBtn">确认分享</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);
        console.log('[shareCourse] Modal appended to body');

        // 点击背景关闭
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.remove();
        });

        // 确认分享
        document.getElementById('confirmShareBtn').addEventListener('click', async () => {
            const classId = document.getElementById('shareClassSelect').value;

            try {
                await apiRequest('/api/teacher/share', {
                    method: 'POST',
                    body: JSON.stringify({
                        course_id: courseId,
                        class_id: classId
                    })
                });
                showToast('分享成功！', 'success');
                modal.remove();
            } catch (error) {
                showToast(error.message, 'error');
            }
        });
    } catch (error) {
        console.error('[shareCourse] Error:', error);
        showToast(error.message, 'error');
    }
};

// ==================== 应用初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
});

// ==================== 加载教材版本 ====================
async function loadTextbookVersions() {
    const versionSelect = document.getElementById('version');
    if (!versionSelect) return;

    try {
        const response = await apiRequest('/textbooks/versions');
        const versions = response.versions || [];

        versionSelect.innerHTML = '<option value="">请选择教材版本</option>';
        versions.forEach(version => {
            const option = document.createElement('option');
            option.value = version.id;
            option.textContent = version.name;
            versionSelect.appendChild(option);
        });
    } catch (error) {
        showToast('加载教材版本失败', 'error');
    }
}

// ==================== 视频生成环境诊断 ====================
/**
 * 运行视频生成环境诊断
 */
async function runVideoDiagnostics() {
    const modal = document.getElementById('diagnosticsModal');
    const resultDiv = document.getElementById('diagnosticsResult');

    modal.style.display = 'flex';
    resultDiv.innerHTML = '<div style="text-align: center; padding: 40px;"><div class="spinner"></div><p style="margin-top: 16px;">正在检查环境...</p></div>';

    try {
        const response = await apiRequest('/api/video/diagnostics');
        const diagnostics = response.diagnostics;

        let html = '';

        // 总体状态
        const statusConfig = {
            'ready': { color: '#10b981', icon: '✅', text: '环境就绪，可以生成视频' },
            'mostly_ready': { color: '#f59e0b', icon: '⚠️', text: '环境基本就绪，部分功能可能受限' },
            'not_ready': { color: '#ef4444', icon: '❌', text: '环境未就绪，无法生成视频' },
            'unknown': { color: '#6b7280', icon: '❓', text: '无法确定环境状态' }
        };

        const status = statusConfig[diagnostics.overall_status] || statusConfig.unknown;

        html += `
            <div style="background: ${status.color}15; border-left: 4px solid ${status.color}; padding: 16px; border-radius: 8px; margin-bottom: 20px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                    <span style="font-size: 24px;">${status.icon}</span>
                    <div>
                        <div style="font-weight: 600; color: ${status.color};">${status.text}</div>
                    </div>
                </div>
            </div>
        `;

        // 各项检查
        html += '<h4 style="margin-bottom: 12px;">详细检查结果</h4>';

        const checkConfig = {
            'tts_config': { name: 'TTS 语音合成配置', icon: '🔊' },
            'ffmpeg': { name: 'FFmpeg 视频处理工具', icon: '🎬' },
            'output_dir': { name: '输出目录权限', icon: '📁' },
            'llm_config': { name: 'LLM API 配置', icon: '🤖' },
            'latex': { name: 'LaTeX 编译器', icon: '📝' }
        };

        for (const [key, config] of Object.entries(checkConfig)) {
            const check = diagnostics.checks[key];
            if (!check) continue;

            const statusColors = {
                'pass': '#10b981',
                'warning': '#f59e0b',
                'fail': '#ef4444'
            };

            const statusIcon = {
                'pass': '✅',
                'warning': '⚠️',
                'fail': '❌'
            };

            const color = statusColors[check.status] || '#6b7280';
            const icon = statusIcon[check.status] || '❓';

            html += `
                <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                        <span>${config.icon}</span>
                        <strong style="flex: 1;">${check.description}</strong>
                        <span style="color: ${color}; font-weight: 600;">${icon}</span>
                    </div>
                    <div style="font-size: 13px; color: #6b7280;">
                        状态: <span style="color: ${color};">${check.status.toUpperCase()}</span>
                    </div>
            `;

            // 显示详细信息
            if (check.details && Object.keys(check.details).length > 0) {
                html += '<div style="margin-top: 8px; font-size: 12px; color: #6b7280;">';
                for (const [detailKey, detailValue] of Object.entries(check.details)) {
                    html += `<div>${detailKey}: ${detailValue}</div>`;
                }
                html += '</div>';
            }

            // 显示修复建议
            if (check.fix && check.status !== 'pass') {
                html += `
                    <div style="margin-top: 8px; padding: 8px; background: #fef3c7; border-radius: 4px; font-size: 12px; color: #92400e;">
                        💡 ${check.fix}
                    </div>
                `;
            }

            html += '</div>';
        }

        resultDiv.innerHTML = html;

    } catch (error) {
        resultDiv.innerHTML = `
            <div style="background: #fee2e2; color: #991b1b; padding: 16px; border-radius: 8px;">
                <strong>诊断失败</strong>
                <p style="margin-top: 8px;">${error.message}</p>
            </div>
        `;
    }
}

/**
 * 关闭诊断弹窗
 */
function closeDiagnosticsModal() {
    const modal = document.getElementById('diagnosticsModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 将函数暴露给全局作用域（HTML中的onclick可以调用）
window.runVideoDiagnostics = runVideoDiagnostics;
window.closeDiagnosticsModal = closeDiagnosticsModal;

// 暴露全局函数
window.viewClassStudents = viewClassStudents;
window.deleteClass = deleteClass;

console.log('[app.js] 全局函数已导出:', {
    viewClassStudents: typeof window.viewClassStudents,
    deleteClass: typeof window.deleteClass
});

