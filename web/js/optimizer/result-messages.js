/** User-facing explanations of backend constraint diagnostics. */
export function explainPlan(result) {
  const fmt=value=>Number(value).toLocaleString('vi-VN',{maximumFractionDigits:4});
  const messages=(result?.issues||[]).map(issue=>{
    switch(issue.kind){
      case 'rate':return `Tốc độ đạt ${fmt(issue.actual_mbps)} Mbps, yêu cầu ${fmt(issue.required_mbps)} Mbps.`;
      case 'battery':return `Pin sau truyền không đủ mức dự trữ tại ${issue.nodes.join(', ')}.`;
      case 'bandwidth':return `Thiếu băng thông còn lại tại ${issue.nodes.join(', ')}.`;
      case 'power':return `Công suất vượt giới hạn tại ${issue.nodes.join(', ')}.`;
      case 'duration':return `Thời gian truyền vượt ${issue.limit_s} giây cho phép.`;
      case 'search_no_route':return issue.topology_connected?'Phương pháp chưa tìm được tuyến; mạng vẫn có kết nối tô-pô. Thử ACO+PSO hoặc đổi seed.':'Hiện không có tuyến nối hai trạm. Kiểm tra pin, tải và thời điểm mạng.';
      case 'no_link':return 'Tuyến có liên kết không khả dụng tại thời điểm hiện tại.';
      case 'invalid_allocation':return 'Phương án cấp phát công suất hoặc băng thông không hợp lệ.';
      default:return 'Phương án chưa thỏa ràng buộc tài nguyên; hãy tìm lại hoặc thay điều kiện mạng.';
    }
  });
  return messages.join(' ')||'Chưa tìm được phương án hợp lệ. Kiểm tra yêu cầu và điều kiện mạng.';
}
