// 简易 Toast 提示
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded-md shadow-lg text-white z-50 transition-opacity duration-300 ${type === 'success' ? 'bg-green-500' : 'bg-red-500'
        }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 设备类型配置（添加图标路径）
const deviceTypeConfig = {
    '交换机': {
        label: '交换机',
        icon: '/static/icons/交换机.png'
    },
    '路由器': {
        label: '路由器',
        icon: '/static/icons/路由器.png'
    },
    '防火墙': {
        label: '防火墙',
        icon: '/static/icons/防火墙.png'
    },
    '负载均衡': {
        label: '负载均衡',
        icon: '/static/icons/负载均衡.png'
    },
    '网管平台': {
        label: '网管平台',
        icon: '/static/icons/网管平台.png'
    },
    '云管平台': {
        label: '云管平台',
        icon: '/static/icons/云管平台.png'
    },
    '服务器集群': {
        label: '服务器集群',
        icon: '/static/icons/服务器集群.png'
    },
    '清洗检测': {
        label: '清洗检测',
        icon: '/static/icons/清洗检测.png'
    },
    '未知': {
        label: '未知设备',
        color: '#9ca3af',
        icon: null
    }
};

// 存储所有分区的Cytoscape实例
const cyInstances = {};
// 当前激活的分区
let activeZone = null;

// 网格 / 锁定布局 全局状态
window.zoneGridVisible = false;     // 网格默认关闭
window.zoneLayoutLocked = true;     // 默认锁定布局（与 dc 一致）。改为 false 即默认解锁（需同步把 HTML 按钮改回橙色“锁定布局”）

// 🌟 新增：坐标整数化工具函数（统一处理，避免重复逻辑）
function normalizeCoord(value) {
    // 处理null/undefined/NaN，默认返回0；有效数值取整
    const num = Number(value);
    return isNaN(num) ? 0 : Math.round(num);
}

// 定义图例渲染函数，使用图标替代颜色块
function renderDeviceLegend() {
    const legendContainer = document.getElementById('device-legend');
    // 设置为两列网格
    legendContainer.style.display = 'grid';
    legendContainer.style.gridTemplateColumns = '1fr 1fr';
    legendContainer.style.gap = '4px 12px'; // 行间距4px，列间距12px
    legendContainer.innerHTML = '';
    Object.values(deviceTypeConfig).forEach(type => {
        const legendItem = document.createElement('div');
        legendItem.className = 'flex items-center py-1';

        let legendContent = '';
        if (type.icon && type.icon !== null) {
            legendContent = `
                <img src="${type.icon}" alt="${type.label}" 
                    class="w-5 h-5 mr-2 object-contain">
                <span class="text-sm text-gray-700">${type.label}</span>
            `;
        } else {
            legendContent = `
                <div class="w-5 h-5 rounded-full mr-2" style="background-color: ${type.color}"></div>
                <span class="text-sm text-gray-700">${type.label}</span>
            `;
        }

        legendItem.innerHTML = legendContent;
        legendContainer.appendChild(legendItem);
    });
}


// 初始化指定分区的Cytoscape实例
function initCytoscapeInstance(zoneId) {
    // 创建容器元素
    const containerId = `cy-${zoneId}`;
    let container = document.getElementById(containerId);

    if (!container) {
        container = document.createElement('div');
        container.id = containerId;
        container.className = 'h-full hidden';
        document.getElementById('topology-containers').appendChild(container);
    }

    // 如果实例已存在，直接返回
    if (cyInstances[zoneId]) {
        return cyInstances[zoneId];
    }

    // 创建新的Cytoscape实例
    const cy = cytoscape({

        wheelSensitivity: 0.1,
        pixelRatio: 1,
        zoom: 1,
        container: container,
        // zoomingEnabled: true, // 新增：允许代码调用缩放
        // userZoomingEnabled: false, // 用户原生滚轮缩放关闭
        selectionType: 'single', // 单次单选：单击只保留当前选中
        selectionModifiers: 'ctrl meta', // 新增：添加 Ctrl+Meta 作为多选
        boxSelectionEnabled: true,                       // 开启矩形框选（拖拽框选多个节点）
        boxSelectSelector: 'node:not([isOrigin]):not([aggregateBtn])',   // 框选只针对设备节点
        selectableElements: 'node:not([isOrigin]):not([aggregateBtn]), edge', // 可被选中的元素

        style: [
            {
                selector: 'node[icon]',
                style: {
                    'shape': 'ellipse',
                    'background-image': 'data(icon)',
                    'background-fit': 'contain',
                    'background-clip': 'none',
                    'background-color': 'transparent',
                    'background-opacity': 0, //隐藏图标下的圆
                    'border-width': 0,
                    'width': 'data(baseSize)',
                    'height': 'data(baseSize)',
                    'label': 'data(name)',
                    'color': '#333',
                    'font-size': 0.5,
                    'text-valign': 'bottom',
                    'text-halign': 'center',
                    'text-margin-y': 0.2,
                    'z-index': 20,            // 比其他元素高，避免被链路和聚合按钮遮挡
                }
            },
            {
                selector: 'node[isUnknown]',
                style: {
                    'shape': 'ellipse',
                    'width': 'data(baseSize)',
                    'height': 'data(baseSize)',
                    'background-color': '#9ca3af',
                    'label': 'data(name)',
                    'color': '#333',
                    'font-size': 0.5,
                    'text-valign': 'bottom',
                    'text-halign': 'center',
                    'text-margin-y': 0.2,
                    'z-index': 20,            // 比其他元素高，避免被链路和聚合按钮遮挡
                }
            },
            // 3. 优化选中节点的样式（关键：明确区分选中状态）
            {
                selector: 'node:selected', // 选中的节点
                style: {
                    'border-color': '#ff4d4f', // 红色边框突出显示
                    'border-width': 0.1, // 边框宽度
                    'border-opacity': 1, // 边框不透明
                    'z-index': 20 // 选中节点置顶显示，比其他元素高，避免被链路和聚合按钮遮挡
                }
            },
            {
                selector: 'edge',
                style: {
                    'width': 0.1,
                    'line-color': '#666',
                    'line-opacity': 0.8,
                    'curve-style': 'bezier',
                    // 'label': 'data(interface)',
                    'text-rotation': 'autorotate',
                    'text-margin-x': 10,
                    'text-margin-y': 10,
                    'font-size': 10,
                    'z-index': 10,            // 置顶显示
                    'color': '#333',
                    'visibility': 'hidden' // 默认隐藏真实边
                }
            },
            {
                // 聚合合并边：蓝色直线（收缩时显示，展开时隐藏）
                selector: 'edge[aggregateLine="true"]',
                style: {
                    'width': 0.1,
                    'line-color': '#1890ff',
                    'target-arrow-color': '#1890ff',
                    'target-arrow-shape': 'none',
                    'curve-style': 'straight', // 直线
                    'z-index': 10,            // 置顶显示
                    'visibility': 'visible' // 默认收缩显示
                }
            },
            {
                // 【聚合悬浮按钮：独立节点，不遮挡任何连线】
                selector: 'node[aggregateBtn="true"]',
                style: {
                    'shape': 'round-rectangle',
                    'width': 0.5,
                    'height': 0.5,
                    'background-color': 'transparent',
                    'background-opacity': 0,
                    'border-width': 0,
                    'label': 'data(label)',      // 显示 ± 数量
                    'font-size': 0.5,
                    'font-weight': 'bold',
                    'color': '#000000',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'z-index': 10,            // 置顶显示
                    'underlay-color': 'transparent',
                    // 'underlay-shape': 'none',
                    'visibility': 'visible'     // 永久显示，可点击
                }
            },
            {
                selector: '.faded',
                style: {
                    'opacity': 0.2,
                    // 'text-opacity': 0.2
                }
            },
            // ========== 新增：控制按住节点时的灰色框 ==========
            {
                selector: 'node:active',
                style: {
                    // 1. 改变大小（填充值）：
                    //    - 正值：比节点大（例如 10px）
                    //    - 负值：比节点小（例如 -2px）
                    //    由于你的节点现在是 1px，若设为 0，灰色框几乎就是 1px 小点
                    'overlay-padding': 0.2,

                    // 2. 改变颜色（默认是黑色 #000，带透明度）
                    'overlay-color': '#888888',

                    // 3. 控制透明度（1=完全不透明，0=完全透明）
                    //    如果你不想看到这个灰色框，直接设为 0 即可关闭
                    'overlay-opacity': 0.25,
                }
            },
            {
                selector: 'edge:active',
                style: {
                    // 1. 改变大小（填充值）：
                    //    - 正值：比节点大（例如 10px）
                    //    - 负值：比节点小（例如 -2px）
                    //    由于你的节点现在是 1px，若设为 0，灰色框几乎就是 1px 小点
                    'overlay-padding': 0.2,

                    // 2. 改变颜色（默认是黑色 #000，带透明度）
                    'overlay-color': '#888888',

                    // 3. 控制透明度（1=完全不透明，0=完全透明）
                    //    如果你不想看到这个灰色框，直接设为 0 即可关闭
                    'overlay-opacity': 0.25,
                }
            },
            {
                selector: 'node[isOrigin]',
                style: {
                    'shape': 'ellipse',
                    'width': 1,               // 自定义圆点大小（像素），可根据需要调整
                    'height': 1,
                    'background-color': 'red',
                    'border-color': '#cc0000',
                    'border-width': 0,
                    // 'label': 'data(label)',   // 显示 "原点" 标签
                    // 'font-size': 8,
                    // 'color': '#333',
                    // 'text-valign': 'bottom',
                    // 'text-halign': 'center',
                    // 'text-margin-y': 3,
                    'z-index': 100,           // 置于顶层，避免被覆盖
                    'events': 'no'            // 完全无交互（可选）
                }
            }
        ]
    });

    // 存储实例
    cyInstances[zoneId] = cy;

    // 鼠标事件
    initCytoscapeEvents(cy, zoneId);
    // 悬停效果
    // initNodeHoverEffects(cy);

    // 初始化该分区的动态网格
    initDynamicGrid(cy, zoneId, '#000000');

    // 该分区实例继承当前锁定状态（默认锁定）
    if (window.zoneLayoutLocked) {
        cy.autoungrabify(true);
    }

    // 滚轮交互：Ctrl+滚轮缩放 / 默认垂直平移 / Shift+滚轮水平平移
    initWheelPan(cy);

    return cy;
}

// ====== 滚轮交互：Ctrl+滚轮缩放 / 默认垂直平移 / Shift+滚轮水平平移（与 dc 一致） ======
function initWheelPan(cy) {
    const container = cy.container();
    // 移除旧监听防止重复绑定（分区重建时用）
    if (container._wheelHandler) {
        container.removeEventListener('wheel', container._wheelHandler);
    }
    // 关闭原生用户滚轮缩放，允许代码缩放
    cy.userZoomingEnabled(false);
    cy.zoomingEnabled(true);

    const PAN_SPEED = 1;  // 平移速度
    const ZOOM_STEP = 2;  // 缩放步长
    const handler = function (e) {
        e.preventDefault();
        if (!container.contains(e.target)) return;

        let deltaY = e.deltaY;
        // 兼容滚动单位：行/页滚动
        if (e.deltaMode === 1) deltaY *= 16;
        else if (e.deltaMode === 2) deltaY *= container.clientHeight;

        // Ctrl / Command 缩放（以鼠标逻辑坐标为锚点）
        if (e.ctrlKey || e.metaKey) {
            const posArr = cy.renderer().projectIntoViewport(e.clientX, e.clientY);
            const mouseLogicPos = { x: posArr[0], y: posArr[1] };

            let newZoom = cy.zoom();
            if (deltaY > 0) {
                newZoom -= ZOOM_STEP;
            } else {
                newZoom += ZOOM_STEP;
            }
            cy.zoom({
                level: newZoom,
                position: mouseLogicPos
            });
            return;
        }

        // Shift + 滚轮：水平左右平移
        if (e.shiftKey) {
            const offset = -deltaY * PAN_SPEED;
            cy.panBy({ x: offset, y: 0 });
            return;
        }

        // 无修饰键：单纯滚轮垂直上下平移画布
        const offset = -deltaY * PAN_SPEED;
        cy.panBy({ x: 0, y: offset });
    };

    container._wheelHandler = handler;
    container.addEventListener('wheel', handler, { passive: false });
}

// ====== 自定义动态网格（适配多分区实例） ======
function initDynamicGrid(cy, zoneId, color) {
    const container = cy.container();
    if (container.querySelector('.cy-dynamic-grid')) return;

    const canvas = document.createElement('canvas');
    canvas.className = 'cy-dynamic-grid';
    canvas.style.position = 'absolute';
    canvas.style.top = 0;
    canvas.style.left = 0;
    canvas.style.pointerEvents = 'none';
    canvas.style.zIndex = 0;
    container.style.position = 'relative';
    container.prepend(canvas);
    canvas.style.display = 'none';

    function drawGrid() {
        if (canvas.style.display === 'none') return;
        const rect = container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;   // 容器隐藏时不画
        canvas.width = rect.width;
        canvas.height = rect.height;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 0.1;

        const zoom = cy.zoom();
        const pan = cy.pan();
        const x1 = -pan.x / zoom, y1 = -pan.y / zoom;
        const x2 = (canvas.width - pan.x) / zoom, y2 = (canvas.height - pan.y) / zoom;

        const step = 1;
        const startX = Math.ceil(x1 / step) * step;
        for (let x = startX; x <= x2; x += step) {
            const sx = x * zoom + pan.x;
            if (sx >= 0 && sx <= canvas.width) { ctx.moveTo(sx, 0); ctx.lineTo(sx, canvas.height); }
        }
        const startY = Math.ceil(y1 / step) * step;
        for (let y = startY; y <= y2; y += step) {
            const sy = y * zoom + pan.y;
            if (sy >= 0 && sy <= canvas.height) { ctx.moveTo(0, sy); ctx.lineTo(canvas.width, sy); }
        }
        ctx.stroke();
    }

    cy.on('zoom pan resize', () => drawGrid());

    // 把画布与重绘函数挂到实例上，供全局开关调用
    cy._gridCanvas = canvas;
    cy._drawGrid = drawGrid;

    // 跟随当前网格总开关的初始状态
    if (window.zoneGridVisible) { canvas.style.display = ''; drawGrid(); }
}

// 全局网格开关：作用于所有分区实例
window.toggleDynamicGrid = function (show) {
    if (show === undefined) show = window.zoneGridVisible;
    window.zoneGridVisible = show;
    Object.keys(cyInstances).forEach(zoneId => {
        const cy = cyInstances[zoneId];
        if (cy && cy._gridCanvas) {
            cy._gridCanvas.style.display = show ? '' : 'none';
            if (show) cy._drawGrid();
            // 若有原点标记节点，随网格显隐（无则忽略）
            const originNode = cy.getElementById && cy.getElementById('origin_marker');
            if (originNode && originNode.length) {
                originNode.style('display', show ? 'element' : 'none');
            }
        }
    });
};

// 添加原点标记（红色圆点，固定在 (0,0)）：不可选中/不可拖动/不参与保存，仅随网格显隐
function addOriginMarker(cy) {
    const originId = 'origin_marker';
    // 避免重复添加
    if (cy.getElementById(originId).length === 0) {
        cy.add({
            group: 'nodes',
            data: {
                id: originId,
                isOrigin: true,
                // label: '原点',
                selectable: false, // 不可被选中
                grabbable: false   // 不可拖动
            },
            position: { x: 0, y: 0 }
        });
        // 默认隐藏（因为网格默认不显示）
        const node = cy.getElementById(originId);
        if (node.length) {
            node.style('display', 'none');
        }
    }
}

// 初始化Cytoscape事件
function initCytoscapeEvents(cy, zoneId) {
    // 节点选中事件（支持单个和多个节点选中，与 dc 一致）
    cy.on('select', 'node', function (event) {
        if (activeZone !== zoneId) return;

        // 排除聚合按钮 / 原点标记等非设备节点
        const selectedNodes = cy.nodes(':selected').not('[aggregateBtn]').not('[isOrigin]');
        if (selectedNodes.length > 0) {
            const lastNode = selectedNodes[selectedNodes.length - 1];
            let showText, sx, sy;
            if (selectedNodes.length === 1) {
                showText = lastNode.data('name');
                sx = Math.round(lastNode.position().x);
                sy = Math.round(lastNode.position().y);
            } else {
                // 多选：显示数量，隐藏坐标
                showText = `${selectedNodes.length}个设备`;
                sx = null;
                sy = null;
            }
            showNodeCoords(sx, sy, showText, '选中');
        }
    });

    // 节点取消选中事件
    cy.on('unselect', 'node', function (event) {
        if (activeZone !== zoneId) return;

        const selectedNodes = cy.nodes(':selected').not('[aggregateBtn]').not('[isOrigin]');
        if (selectedNodes.length === 0) {
            document.getElementById('node-coords').textContent = '未选中节点';
        } else {
            // 更新剩余选中节点的显示
            const lastNode = selectedNodes[selectedNodes.length - 1];
            let showText, sx, sy;
            if (selectedNodes.length === 1) {
                showText = lastNode.data('name');
                sx = Math.round(lastNode.position().x);
                sy = Math.round(lastNode.position().y);
            } else {
                showText = `${selectedNodes.length}个设备`;
                sx = null;
                sy = null;
            }
            showNodeCoords(sx, sy, showText, '选中');
        }
    });

    // 点击空白处取消所有选中（简化逻辑，依赖样式定义）
    cy.on('click', function (event) {
        if (activeZone !== zoneId && event.target !== cy) return;

        if (event.target === cy) {
            cy.nodes().unselect(); // 仅调用unselect，样式由CSS控制
            document.getElementById('node-coords').textContent = '未选中节点';
        }
    });

    // 节点拖动事件
    cy.on('drag', 'node', function (event) {
        if (activeZone !== zoneId) return;

        // 多选拖拽：仅提示选中数量，不显示坐标
        const selectedNodes = cy.nodes(':selected').not('[aggregateBtn]').not('[isOrigin]');
        if (selectedNodes.length > 1) {
            showNodeCoords(null, null, `${selectedNodes.length}个设备`, '拖动中');
            return;
        }

        const node = event.target;
        const deviceName = node.data('name');
        // 🌟 优化：坐标整数化（仅显示）
        const x = normalizeCoord(node.position().x);
        const y = normalizeCoord(node.position().y);
        showNodeCoords(x, y, deviceName, '拖动中');
    });

    // 节点拖动结束事件
    cy.on('dragfree', 'node', function (event) {
        if (activeZone !== zoneId) return;

        // 多选拖拽：仅提示选中数量，不显示坐标
        const selectedNodes = cy.nodes(':selected').not('[aggregateBtn]').not('[isOrigin]');
        if (selectedNodes.length > 1) {
            showNodeCoords(null, null, `${selectedNodes.length}个设备`, '停止拖动');
            return;
        }

        const node = event.target;
        const deviceName = node.data('name');
        // 🌟 关键优化：拖动结束后强制节点坐标为整数
        const x = normalizeCoord(node.position().x);
        const y = normalizeCoord(node.position().y);
        node.position({ x, y }); // 覆盖节点坐标为整数
        showNodeCoords(x, y, deviceName, '停止拖动');
    });

    // 节点悬停显示提示框
    cy.on('mouseover', 'node', function (event) {
        if (activeZone !== zoneId) return;

        const node = event.target;
        const data = node.data();

        // 聚合按钮：不显示 tooltip，仅可点击展开/收起
        if (data.aggregateBtn) return;

        // 高亮连接的节点和边（设备节点）
        const connectedEdges = node.connectedEdges();
        const connectedNodes = node.connectedNodes().add(node);
        cy.nodes().not(connectedNodes).addClass('faded');
        cy.edges().not(connectedEdges).addClass('faded');

        // 计算提示框位置
        const tooltip = document.getElementById('node-tooltip');
        const cyContainer = document.getElementById(`cy-${zoneId}`);
        const renderedPos = node.renderedPosition();
        const containerRect = cyContainer.getBoundingClientRect();

        let x = containerRect.left + renderedPos.x + 20;
        let y = containerRect.top + renderedPos.y + 10;

        // 🌟 优化：提示框中坐标整数化
        const nodeX = normalizeCoord(node.position().x);
        const nodeY = normalizeCoord(node.position().y);

        // 填充提示框内容
        tooltip.innerHTML = `
            <div class="tooltip-title">${data.name || '未知设备'}</div>
            <div class="tooltip-row">
                <span class="tooltip-label">厂商：</span>${data.vendor || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">类型：</span>${data.type || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">型号：</span>${data.model || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">IP：</span>${data.ip || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">MAC：</span>${data.mac || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">SN：</span>${data.sn || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">数据中心：</span>${data.data_center || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">坐标：</span>(${nodeX}, ${nodeY})
            </div>
        `;

        // 视口边界检查
        const tooltipRect = tooltip.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        if (x + tooltipRect.width > viewportWidth) {
            x = containerRect.left + renderedPos.x - tooltipRect.width - 20;
        }

        if (y + tooltipRect.height > viewportHeight) {
            y = containerRect.top + renderedPos.y - tooltipRect.height - 10;
        }

        tooltip.style.left = `${x}px`;
        tooltip.style.top = `${y}px`;
        tooltip.style.opacity = 1;
    });

    // 鼠标离开节点隐藏提示框
    cy.on('mouseout', 'node', function () {
        if (activeZone !== zoneId) return;

        cy.nodes().removeClass('faded');
        cy.edges().removeClass('faded');
        document.getElementById('node-tooltip').style.opacity = 0;
    });

    // 链路悬停效果
    cy.on('mouseover', 'edge', function (event) {
        if (activeZone !== zoneId) return;

        const edge = event.target;
        const data = edge.data();

        const sourceNode = edge.source();
        const targetNode = edge.target();

        cy.nodes().not(sourceNode).not(targetNode).addClass('faded');
        cy.edges().not(edge).addClass('faded');

        const tooltip = document.getElementById('node-tooltip');
        const position = event.originalEvent;
        const x = position.pageX + 10;
        const y = position.pageY + 10;

        tooltip.innerHTML = `
            <div class="tooltip-title">链路</div>
            <div class="tooltip-row">
                <span class="tooltip-label">本端设备：</span>${sourceNode.data('name') || data.source}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">本端接口：</span>${data.local_intf || '未知'}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">远端设备：</span>${targetNode.data('name') || data.target}
            </div>
            <div class="tooltip-row">
                <span class="tooltip-label">远端接口：</span>${data.remote_intf || '未知'}
            </div>
        `;

        tooltip.style.left = `${x}px`;
        tooltip.style.top = `${y}px`;
        tooltip.style.opacity = 1;
    });

    // 鼠标离开链路
    cy.on('mouseout', 'edge', function () {
        if (activeZone !== zoneId) return;

        cy.nodes().removeClass('faded');
        cy.edges().removeClass('faded');
        document.getElementById('node-tooltip').style.opacity = 0;
    });
}

// 创建拓扑节点和链路
function createTopologyNodes(cy, zoneId, devices, connections) {
    console.debug(`${zoneId}`, `设备数量: ${devices.length}, 链路数量: ${connections.length}`);

    // 清空现有元素
    cy.remove(cy.elements());

    // 检查是否有坐标数据
    const hasCoordinates = devices.some(device =>
        device.x !== null && device.x !== undefined &&
        device.y !== null && device.y !== undefined &&
        !isNaN(device.x) && !isNaN(device.y)
    );

    const nodes = devices
        .filter(device => device.id && device.name)
        .map(device => {
            if (!device.type || device.type === '未知') {
                device.type = '未知';
            }
            const config = deviceTypeConfig[device.type];
            const baseSize = 1;
            const hoverSize = 1;

            const nodeData = {
                id: device.id,
                name: device.name,
                vendor: device.vendor,
                model: device.model,
                ip: device.ip,
                mac: device.mac,
                sn: device.sn,
                data_center: device.dc,
                type: device.type,
                color: config.color,
                baseSize: baseSize,
                hoverSize: hoverSize
            };

            if (device.type === '未知') {
                nodeData.isUnknown = true;
            } else {
                nodeData.icon = config.icon;
            }

            const node = {
                group: 'nodes',
                data: nodeData
            };

            // 🌟 优化：节点初始坐标整数化
            if (hasCoordinates) {
                node.position = {
                    x: normalizeCoord(device.x),
                    y: normalizeCoord(device.y)
                };
            }

            return node;
        });

    // 添加节点和链路
    cy.add([...nodes, ...connections]);

    // 应用布局
    let layout;
    if (hasCoordinates) {
        layout = cy.layout({ name: 'preset' });
    } else {
        layout = cy.layout({
            name: 'breadthfirst',
            directed: true,
            // padding: 30,
            spacingFactor: 6,// 节点间距
            avoidOverlap: true,
            boundingBox: { x1: -30, y1: -20, w: 60, h: 40 },  // 关键：小尺度

        });
    }

    layout.run();

    // 添加原点标记（固定在 (0,0)，默认隐藏，仅网格显示时可见）
    addOriginMarker(cy);

}

// 更新设备列表
function updateDeviceList(devices, zoneId) {
    const deviceList = document.getElementById('device-list');
    deviceList.innerHTML = '';

    devices.forEach(device => {
        const deviceItem = document.createElement('div');
        deviceItem.className = 'p-2 border rounded hover:bg-gray-100 cursor-pointer transition-colors';

        deviceItem.innerHTML = `
            <div class="text-xs">${device.name ? device.name : '暂无设备，请补充后再试！'}</div>
            <div class="text-xs text-gray-600">${device.vendor || '未知厂商'} | ${device.model || '未知型号'}</div>
        `;

        // 点击设备列表项 - 聚焦拓扑节点
        deviceItem.addEventListener('click', () => {
            const cy = cyInstances[zoneId];
            if (!cy) return;

            // 取消所有节点的选中状态
            cy.nodes().unselect();

            // 选中目标节点
            const targetNode = cy.nodes(`[id="${device.id}"]`);
            if (targetNode.length > 0) {
                targetNode.select(); // 仅调用select，样式由CSS控制
                // 等首帧渲染完成后再设视口，避免容器隐藏/首帧把 center 覆盖导致“第一次点击不跳转”
                cy.ready(() => {
                    cy.animate({ center: { eles: targetNode }, zoom: 25 }, { duration: 150 });
                });
                // 🌟 优化：坐标整数化
                const x = normalizeCoord(device.x || targetNode.position().x);
                const y = normalizeCoord(device.y || targetNode.position().y);
                showNodeCoords(x, y, device.name);
            }
        });

        deviceList.appendChild(deviceItem);
    });
}

// 显示节点坐标
function showNodeCoords(x, y, deviceName, status = '选中') {
    // 多选时坐标传 null/undefined，统一显示为 —
    const intX = (x === null || x === undefined) ? '—' : normalizeCoord(x);
    const intY = (y === null || y === undefined) ? '—' : normalizeCoord(y);
    const coordsElement = document.getElementById('node-coords');
    coordsElement.textContent = `${status} - ${deviceName} - X: ${intX}, Y: ${intY}`;
}

// 按需加载分区数据（缓存支持）
// 修改 loadZoneData 函数，增加 forceReload 参数
function loadZoneData(zoneId, forceReload = false) {
    // 如果强制刷新，则销毁已有实例并清空缓存
    if (forceReload && cyInstances[zoneId]) {
        cyInstances[zoneId].destroy();
        delete cyInstances[zoneId];
        // 同时移除对应的容器元素
        const container = document.getElementById(`cy-${zoneId}`);
        if (container) container.remove();
    }

    // 如果实例已存在且包含元素，直接返回 resolved Promise
    if (cyInstances[zoneId] && cyInstances[zoneId].elements().length > 0) {
        return Promise.resolve(cyInstances[zoneId]);
    }

    window.zoneTopoLoading = true;
    return fetch(`/topology/get_zone_topology_data?zone_id=${zoneId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const nodes = (data.nodes || []);
                const links = (data.links || []);
                // 空分区（分区存在但暂无互联数据）：正常渲染空图并提示，不再误报错误
                if (nodes.length === 0) {
                    const cy = initCytoscapeInstance(zoneId);
                    createTopologyNodes(cy, zoneId, [], []);
                    window.zoneTopoLoading = false;
                    showToast(`已加载「${data.zone_name || zoneId}」：暂无互联数据，请补充后再试！`, 'success');
                    return cy;
                }
                const cy = initCytoscapeInstance(zoneId);
                const formattedConnections = links.map(conn => ({
                    group: 'edges',
                    data: conn
                }));
                createTopologyNodes(cy, zoneId, nodes, formattedConnections);
                mergeMultipleEdges(cy);
                window.zoneTopoLoading = false;
                // 有节点但无链路：仍渲染节点，并提示“暂无互联数据”
                if (links.length === 0 && data.message) {
                    showToast(data.message, 'success');
                }
                // 加载成功：提示设备数量与链路数量
                showToast(`已加载「${data.zone_name || zoneId}」：设备 ${nodes.length} 台，链路 ${links.length} 条`, 'success');
                return cy;
            } else {
                window.zoneTopoLoading = false;
                // 后端业务错误（如：分区「X」在互联表的「所属分区」列中不存在）
                throw new Error(data.error || '加载拓扑数据失败');
            }
        })
        .catch(error => {
            window.zoneTopoLoading = false;
            console.error(`加载分区${zoneId}数据失败:`, error);
            throw error;
        });
}


// 切换分区显示（按需加载）
function switchZone(zoneId, zoneName, forceReload = false) {
    // 隐藏初始提示
    document.getElementById('initial-message').classList.add('hidden');

    // 先隐藏所有分区容器
    Object.keys(cyInstances).forEach(id => {
        const container = document.getElementById(`cy-${id}`);
        if (container) {
            container.classList.add('hidden');
        }
    });

    // 确保当前分区容器被创建（可能还未加载数据）
    const activeContainer = document.getElementById(`cy-${zoneId}`);
    if (activeContainer) {
        activeContainer.classList.remove('hidden');
    }

    // 更新当前激活分区
    activeZone = zoneId;

    // 加载数据（传递 forceReload）
    loadZoneData(zoneId, forceReload).then(cy => {
        if (activeZone !== zoneId) return;

        const container = document.getElementById(`cy-${zoneId}`);
        if (container) {
            container.classList.remove('hidden');
        }

        // 切换分区后，按当前网格开关重绘该分区网格（容器刚显示，需手动触发一次）
        if (cy._drawGrid) cy._drawGrid();

        // 首次显示该分区：自动居中并缩放至完整拓扑（容器刚可见，先 resize 再 fit）
        if (!cy._fitted && cy.nodes().length > 0) {
            cy.resize();
            cy.fit(undefined, 60);
            cy._fitted = true;
        }

        // 更新设备列表
        const devices = cy.nodes().map(node => ({
            id: node.data('id'),
            name: node.data('name'),
            model: node.data('model'),
            vendor: node.data('vendor'),
            x: normalizeCoord(node.position().x),
            y: normalizeCoord(node.position().y)
        }));
        updateDeviceList(devices, zoneId);
        document.getElementById('node-coords').textContent = '未选中节点';
    }).catch(error => {
        // 将后端返回的业务错误（如"分区「X」在互联表的「所属分区」列中不存在"）以 toast 清晰提示给用户
        showToast(`加载分区[${zoneName}]失败: ${error.message || error}`, 'error');
        resetToInitialState();
        document.getElementById('zone-selector').value = '';
    });
}

// fetch 加载分区列表
function loadZones() {
    fetch('/topology/get_zones')
        .then(response => response.json())
        .then(data => {
            if (data.success && data.zones && data.zones.length > 0) {
                const selector = document.getElementById('zone-selector');

                // 填充下拉框
                data.zones.forEach(zone => {
                    const option = document.createElement('option');
                    option.value = zone.id;
                    option.textContent = zone.name;
                    selector.appendChild(option);
                });

                // 绑定下拉框事件
                selector.addEventListener('change', function () {
                    const selectedZoneId = this.value;
                    const selectedZoneName = this.options[this.selectedIndex].text;
                    if (selectedZoneId) {
                        switchZone(selectedZoneId, selectedZoneName);
                    } else {
                        // 选中默认选项（value=""）：重置为初始状态
                        resetToInitialState();
                    }
                });

                // 不再自动预加载所有分区数据，改为按需加载
            }
        })
        .catch(error => console.error('获取分区列表失败:', error));
}

// 重置为初始状态函数
function resetToInitialState() {
    // 1. 隐藏所有分区拓扑容器
    Object.keys(cyInstances).forEach(id => {
        const container = document.getElementById(`cy-${id}`);
        if (container) {
            container.classList.add('hidden');
        }
    });

    // 2. 显示初始提示框
    const initialMsg = document.getElementById('initial-message');
    if (initialMsg) {
        initialMsg.classList.remove('hidden');
    }

    // 3. 重置当前激活分区
    activeZone = null;

    // 4. 清空设备列表
    const deviceList = document.getElementById('device-list');
    if (deviceList) {
        deviceList.innerHTML = '';
    }

    // 5. 清空坐标显示
    document.getElementById('node-coords').textContent = '未选中节点';
}
// 存储：按钮ID → { 合并边, 真实边列表 }
let aggregateMap = {};

/**
 * 完美版：≥2条聚合 | 蓝色直线合并边 | 悬浮按钮无遮挡 | 自由切换
 * @param {Cytoscape} cy - 当前分区的Cytoscape实例
 */
function mergeMultipleEdges(cy) {
    // 新增：校验cy实例有效性
    if (!cy || typeof cy !== 'object' || !cy.remove) {
        console.warn('mergeMultipleEdges: 无效的Cytoscape实例', cy);
        return;
    }

    // 清空旧元素
    aggregateMap = {};
    cy.remove('node[aggregateBtn="true"]');
    cy.remove('edge[aggregateLine="true"]');

    // 按节点对分组边
    const edgeGroups = {};
    cy.edges().forEach(edge => {
        const source = edge.source().id();
        const target = edge.target().id();
        const groupKey = [source, target].sort().join('_');
        edgeGroups[groupKey] ||= [];
        edgeGroups[groupKey].push(edge);
    });

    // 生成合并边+按钮
    Object.values(edgeGroups).forEach(edgeList => {
        // 单条边：恢复默认曲线样式并显示（清除可能残留的偏移曲线样式）
        if (edgeList.length < 2) {
            edgeList.forEach(e => e.style({
                'curve-style': 'bezier',
                'visibility': 'visible'
            }));
            return;
        }

        const firstEdge = edgeList[0];
        const sourceId = firstEdge.source().id();
        const targetId = firstEdge.target().id();
        const key = [sourceId, targetId].sort().join('_');

        // 1. 创建蓝色合并边（直线）
        const aggregateLine = cy.add({
            group: 'edges',
            data: {
                id: `agg_line_${key}`,
                source: sourceId,
                target: targetId,
                aggregateLine: 'true'
            }
        });

        // 2. 创建中点悬浮按钮（无遮挡）
        const sourceNode = firstEdge.source();
        const targetNode = firstEdge.target();
        const midX = (sourceNode.position().x + targetNode.position().x) / 2;
        const midY = (sourceNode.position().y + targetNode.position().y) / 2;

        const aggregateBtn = cy.add({
            group: 'nodes',
            data: {
                id: `agg_btn_${key}`,
                aggregateBtn: 'true',
                label: `+ ${edgeList.length}`,
                count: edgeList.length,   // 供 tooltip 显示并行链路数
                selectable: false,        // 不可被选中
                grabbable: false          // 不可被拖动
            },
            position: { x: midX, y: midY }
        });

        // 存储关联关系
        aggregateMap[aggregateBtn.id()] = {
            line: aggregateLine,
            edges: edgeList
        };

        // 给每条并行边设置对称偏移的贝塞尔曲线，展开后自动错开不重合（参考 topology_dc 算法）
        const edgeCount = edgeList.length;
        edgeList.forEach((edge, index) => {
            // 以组中间为原点，向两侧对称分布偏移量（正负交替，避免重合）
            const offset = (index - (edgeCount - 1) / 2) * 1; // 步长(模型单位)，可按坐标尺度调整
            edge.style({
                'curve-style': 'unbundled-bezier',
                'control-point-distances': [offset],
                'control-point-weights': [0.5],
                'visibility': 'hidden' // 默认收缩隐藏，展开时显示
            });
            edge.data('merged', 'true');
        });
    });

    // 内部函数也能继承外部的cy参数
    function bindToggleEvent() {
        cy.off('click', 'node[aggregateBtn="true"]');
        cy.on('click', 'node[aggregateBtn="true"]', evt => {
            const btn = evt.target;
            const data = aggregateMap[btn.id()];
            if (!data) return;

            const { line, edges } = data;
            const isMerged = edges[0].data('merged') === 'true';

            if (isMerged) {
                // 👉 展开：隐藏蓝色合并边，显示所有黑色曲线
                line.style('visibility', 'hidden');
                edges.forEach(edge => {
                    edge.data('merged', 'false');
                    edge.style('visibility', 'visible');
                });
                btn.data('label', `- ${edges.length}`);
            } else {
                // 👉 合并：显示蓝色合并边，隐藏所有黑色曲线
                line.style('visibility', 'visible');
                edges.forEach(edge => {
                    edge.data('merged', 'true');
                    edge.style('visibility', 'hidden');
                });
                btn.data('label', `+ ${edges.length}`);
            }
        });
    }

    bindToggleEvent();

    // ========== 新增：聚合按钮位置更新逻辑 ==========
    // 更新所有聚合按钮位置到线路中点
    function updateAggregateBtnPositions() {
        Object.keys(aggregateMap).forEach(btnId => {
            const { edges } = aggregateMap[btnId];
            const edge = edges[0];
            const sourceNode = edge.source();
            const targetNode = edge.target();
            const midX = (sourceNode.position().x + targetNode.position().x) / 2;
            const midY = (sourceNode.position().y + targetNode.position().y) / 2;
            const btnNode = cy.getElementById(btnId);
            if (btnNode.length) {
                btnNode.position({ x: midX, y: midY });
            }
        });
    }

    // 初始化更新按钮位置
    updateAggregateBtnPositions();

    // 监听节点拖动，实时更新聚合按钮位置
    cy.off('drag', 'node', updateAggregateBtnPositions);
    cy.off('dragfree', 'node', updateAggregateBtnPositions);
    cy.on('drag', 'node', updateAggregateBtnPositions);
    cy.on('dragfree', 'node', updateAggregateBtnPositions);
    // ========== 新增结束 ==========
}


/**
 * 点击按钮：切换展开/合并
 */
function bindToggleEvent() {
    cy.off('click', 'node[aggregateBtn="true"]');
    cy.on('click', 'node[aggregateBtn="true"]', evt => {
        const btn = evt.target;
        const data = aggregateMap[btn.id()];
        if (!data) return;

        const { line, edges } = data;
        const isMerged = edges[0].data('merged') === 'true';

        if (isMerged) {
            // 👉 展开：隐藏蓝色合并边，显示所有黑色曲线
            line.style('visibility', 'hidden');
            edges.forEach(edge => {
                edge.data('merged', 'false');
                edge.style('visibility', 'visible');
            });
            btn.data('label', `- ${edges.length}`);
        } else {
            // 👉 合并：显示蓝色合并边，隐藏所有黑色曲线
            line.style('visibility', 'visible');
            edges.forEach(edge => {
                edge.data('merged', 'true');
                edge.style('visibility', 'hidden');
            });
            btn.data('label', `+ ${edges.length}`);
        }
    });
}

document.addEventListener('DOMContentLoaded', function () {
    // 渲染设备图例
    renderDeviceLegend();
    // 加载分区列表
    loadZones();



    // 保存拓扑按钮事件
    document.getElementById('save-topology').addEventListener('click', function () {
        if (!activeZone) {
            showToast('请先选择一个分区', 'error');
            return;
        }

        const cy = cyInstances[activeZone];
        if (!cy) {
            showToast('分区图表未就绪', 'error');
            return;
        }

        const btn = this;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span>保存中...</span>';
        btn.disabled = true;

        // 获取所有节点的位置信息（排除聚合按钮与原点标记，原点不可被保存）
        const nodes = cy.nodes()
            .filter(node => !node.data('aggregateBtn') && !node.data('isOrigin'))
            .map(node => ({
                id: node.id(),
                name: node.data('name'),
                x: normalizeCoord(node.position().x),
                y: normalizeCoord(node.position().y)
            }));
        // console.log('保存的节点:', nodes);
        // 发送到服务器保存
        fetch_save_zone = '/topology/save_zone_topology'
        fetch(fetch_save_zone, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                zone_id: activeZone,
                devices: nodes
            })
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.not_found.length > 0) {
                        alert(`坐标表的"${activeZone}"分区中未找到以下设备（共${data.not_found.length}个），请添加后重新保存:\n${data.not_found.join('\n')}`);
                        showToast('部分拓扑保存成功，请检查后重新保存', 'success');
                    } else {
                        // console.log('拓扑保存成功:', data);
                        showToast('拓扑保存成功', 'success');
                    }
                } else {
                    // console.error('拓扑保存失败:', data);
                    showToast('请关闭表格后重试: ' + data.error, 'error');
                }
            })
            .catch(error => {
                // console.error('拓扑保存请求失败:', error);
                showToast('请检查前后端路由是否正确: ' + fetch_save_zone, 'error');
            })
            .finally(() => {
                btn.innerHTML = originalHtml;
                btn.disabled = false;
            });
    });

    // 方案A：导出「当前视口」，并直接复用画布上已有的网格 canvas（1:1 叠加，绝不重画）
    // PNG导出功能
    document.getElementById('exportPngBtn').addEventListener('click', async function (event) {
        if (!activeZone) {
            showToast('请先选择一个分区', 'error');
            return;
        }

        const cy = cyInstances[activeZone];
        if (!cy) {
            showToast('分区图表未就绪', 'error');
            return;
        }

        // 必须在拓扑页面且生成/加载完成才能导出，避免导出损坏/空白图
        const zoneContainer = cy.container();
        if (window.zoneTopoLoading) {
            showToast('拓扑生成/加载中，请稍后再导出', 'error');
            return;
        }
        if (!zoneContainer || zoneContainer.style.display === 'none' || zoneContainer.offsetWidth === 0) {
            showToast('当前分区尚未显示，无法导出', 'error');
            return;
        }

        const btn = event.currentTarget;
        const originalHtml = btn.innerHTML;
        btn.innerHTML = '<span>导出中...</span>';
        btn.disabled = true;

        try {
            // 导出前：隐藏“原点”控件节点（非拓扑数据）；隐藏 tooltip；清空选中（去掉红圈）
            // 说明：聚合按钮保留显示（用户要求）；选中与 tooltip 导出后不再恢复
            const origin = cy.getElementById('origin_marker');
            const originWasVisible = origin.length && origin.style('display') !== 'none';
            if (origin.length) origin.style('display', 'none');

            // 隐藏节点 tooltip（DOM 浮层，导出后不恢复）
            const nodeTip = document.getElementById('node-tooltip');
            if (nodeTip) nodeTip.style.opacity = '0';

            // 清空当前选中，红圈/选中边框不进入 PNG（导出后不恢复选中）
            cy.elements().unselect();

            // 清除 hover/选中产生的 .faded 高亮（高亮节点与链路），导出后不恢复
            cy.elements().removeClass('faded');


            const baseDataUrl = cy.png({
                full: true,
                scale: 30,
                bg: 'white',
            });

            // 恢复原点显示状态（网格开则显示，否则隐藏）
            if (origin.length) origin.style('display', originWasVisible ? 'element' : 'none');
            // 注：聚合按钮保留显示；选中状态与 tooltip 导出后不恢复

            // 导出 PNG 不再叠加网格，仅保留白底拓扑
            const finalDataUrl = baseDataUrl;

            // 文件名追加本地时间戳（YYYYMMDDHHMMSS）
            const d = new Date();
            const pad2 = n => String(n).padStart(2, '0');
            const ts = `${d.getFullYear()}${pad2(d.getMonth() + 1)}${pad2(d.getDate())}${pad2(d.getHours())}${pad2(d.getMinutes())}${pad2(d.getSeconds())}`;

            const link = document.createElement('a');
            link.href = finalDataUrl;
            link.download = `分区拓扑-[${activeZone}]-${ts}.png`;
            link.click();

            URL.revokeObjectURL(link.href);
            link.remove();
            showToast('PNG 导出成功', 'success');
        } catch (e) {
            console.error('PNG导出异常：', e);
            showToast('导出失败，请重试', 'error');
        } finally {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        }
    });

    document.getElementById('refreshZoneBtn').addEventListener('click', function () {
        const btn = this;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span>刷新中...</span>';

        if (!activeZone) {
            showToast('请先选择一个分区', 'error');
            btn.disabled = false;
            btn.innerHTML = originalHtml;
            return;
        }

        // 调用后端刷新缓存
        fetch('/refresh_cache', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keys: ['zone_topology_data'] })
        })
            .then(response => {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error(data.message || '缓存刷新失败');
                // 重新加载当前分区（强制刷新）
                const zoneName = document.getElementById('zone-selector').options[
                    document.getElementById('zone-selector').selectedIndex
                ].text;
                switchZone(activeZone, zoneName, true); // 需要修改 switchZone 支持 forceReload
                showToast('分区拓扑已刷新（缓存已更新）', 'success');
            })
            .catch(error => {
                console.error('刷新失败:', error);
                showToast('刷新失败: ' + error.message, 'error');
            })
            .finally(() => {
                btn.disabled = false;
                btn.innerHTML = originalHtml;
            });
    });


    // ====== 显示网格 开关 ======
    const toggleGridBtn = document.getElementById('toggleGridBtn');
    if (toggleGridBtn) {
        toggleGridBtn.addEventListener('click', () => {
            if (!activeZone) {
                showToast('请先选择一个分区', 'error');
                return;
            }
            const show = !window.zoneGridVisible;
            if (typeof window.toggleDynamicGrid === 'function') {
                window.toggleDynamicGrid(show);
            }
            toggleGridBtn.querySelector('span').textContent = show ? '隐藏网格' : '显示网格';
        });
    }

    // ====== 锁定 / 解锁布局 ======
    // 作用于所有分区实例；新切换/刷出的分区会在 initCytoscapeInstance 中自动继承当前状态
    function applyZoneLayoutLock(locked) {
        Object.keys(cyInstances).forEach(zoneId => {
            const cy = cyInstances[zoneId];
            if (cy) cy.autoungrabify(locked);
        });
        window.zoneLayoutLocked = locked;
    }

    const lockLayoutBtn = document.getElementById('lockLayoutBtn');
    if (lockLayoutBtn) {
        lockLayoutBtn.addEventListener('click', () => {
            if (!activeZone) {
                showToast('请先选择一个分区', 'error');
                return;
            }
            const locked = !window.zoneLayoutLocked;
            applyZoneLayoutLock(locked);

            const span = lockLayoutBtn.querySelector('span');
            if (locked) {
                // 进入锁定：禁止拖动，仅保留查看
                span.textContent = '解锁布局';
                showToast('布局已锁定：节点不可拖动，仅可查看 tooltip 信息', 'success');
            } else {
                // 解除锁定：恢复可调整拓扑
                span.textContent = '锁定布局';
                showToast('布局已解锁：可重新拖动并调整拓扑', 'success');
            }
        });
    }


    // 窗口大小改变时隐藏提示框
    window.addEventListener('resize', function () {
        document.getElementById('node-tooltip').style.opacity = 0;
    });


});