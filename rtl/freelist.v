// Simplified BOOM-style rename freelist.
//
// Maintains a bitmask of free physical registers. One allocation and one
// deallocation port, plus single-tag branch snapshot/rollback.
//
// Environment contract (see verif/props.vh for the machine-checked form):
//   A1: dealloc_valid -> the named preg is currently allocated (not free)
//   A2: br_rollback   -> no concurrent alloc_req or dealloc_valid
module freelist #(
    parameter NUM_PREGS = 8,
    parameter PREG_W    = 3
) (
    input  wire                 clk,
    input  wire                 reset,

    input  wire                 alloc_req,
    output wire                 alloc_valid,
    output wire [PREG_W-1:0]    alloc_preg,

    input  wire                 dealloc_valid,
    input  wire [PREG_W-1:0]    dealloc_preg,

    input  wire                 br_snapshot,
    input  wire                 br_rollback,

    output wire [NUM_PREGS-1:0] free_mask_o,
    output wire [NUM_PREGS-1:0] snapshot_o
);

  reg [NUM_PREGS-1:0] free_mask;
  reg [NUM_PREGS-1:0] snapshot;

  // Lowest-set-bit select: isolate the least significant free preg.
  wire [NUM_PREGS-1:0] sel_oh  = free_mask & (~free_mask + 1'b1);
  wire                 any_free = |free_mask;

  assign alloc_valid = alloc_req & any_free;

  // One-hot to binary encode.
  integer i;
  reg [PREG_W-1:0] enc;
  always @* begin
    enc = {PREG_W{1'b0}};
    for (i = 0; i < NUM_PREGS; i = i + 1)
      if (sel_oh[i]) enc = i[PREG_W-1:0];
  end
  assign alloc_preg = enc;

  wire [NUM_PREGS-1:0] dealloc_oh =
      dealloc_valid ? ({{(NUM_PREGS-1){1'b0}}, 1'b1} << dealloc_preg)
                    : {NUM_PREGS{1'b0}};
  wire [NUM_PREGS-1:0] alloc_clr =
      alloc_valid ? sel_oh : {NUM_PREGS{1'b0}};

  wire [NUM_PREGS-1:0] next_mask = (free_mask & ~alloc_clr) | dealloc_oh;

  always @(posedge clk) begin
    if (reset) begin
      free_mask <= {NUM_PREGS{1'b1}};
      snapshot  <= {NUM_PREGS{1'b1}};
    end else begin
      if (br_rollback) free_mask <= snapshot;
      else             free_mask <= next_mask;
      if (br_snapshot) snapshot <= next_mask;
    end
  end

  assign free_mask_o = free_mask;
  assign snapshot_o  = snapshot;
endmodule
