import * as echarts from "echarts/core";
import { CandlestickChart, LineChart, BarChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  ToolboxComponent,
  MarkLineComponent,
  MarkAreaComponent,
  VisualMapComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  CandlestickChart, LineChart, BarChart, HeatmapChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkPointComponent,
  ToolboxComponent, MarkLineComponent, MarkAreaComponent,
  VisualMapComponent,
  CanvasRenderer,
]);

export const CHART_GROUP = "quant-charts";

let _connected = false;

export function connectCharts() {
  if (!_connected) {
    echarts.connect(CHART_GROUP);
    _connected = true;
  }
}

export { echarts };

/**
 * Lightweight ECharts tooltip formatter param shape.
 *
 * We keep a local structural type instead of importing echarts' deep
 * `TopLevelFormatterParams` union so chart components can drop the
 * `// eslint-disable-next-line @typescript-eslint/no-explicit-any` comments
 * without pulling in the full echarts type tree at editor-time.
 */
export interface ChartFormatterParam {
  axisValue?: string;
  seriesName?: string;
  value?: number | string | (number | string)[];
  marker?: string;
  color?: string;
  dataIndex?: number;
  seriesIndex?: number;
}

export type ChartFormatterParams = ChartFormatterParam | ChartFormatterParam[];

