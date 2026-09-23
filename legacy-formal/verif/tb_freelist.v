// Constrained-random simulation harness for the rename freelist.
//
// Stimulus is generated so the environment assumptions in verif/checker.vh hold
// by construction: deallocations only name currently-allocated pregs (A1) and
// rollbacks never coincide with allocation or deallocation (A2).
//
// Machine-readable output, consumed by chia_loop/simrun.py:
//   ASSERT_FAIL prop=<name> cycle=<n>
//   SUMMARY cycles=<n> fails=<n>
//   RESULT PASS | RESULT FAIL
`timescale 1ns/1ps

module tb_freelist;

  localparam NUM_PREGS = 8;
  localparam PREG_W    = 3;

  reg                  clk = 1'b0;
  reg                  reset = 1'b1;
  reg                  alloc_req = 1'b0;
  reg                  dealloc_valid = 1'b0;
  reg  [PREG_W-1:0]    dealloc_preg = {PREG_W{1'b0}};
  reg                  br_snapshot = 1'b0;
  reg                  br_rollback = 1'b0;

  wire                 alloc_valid;
  wire [PREG_W-1:0]    alloc_preg;
  wire [NUM_PREGS-1:0] free_mask_o;
  wire [NUM_PREGS-1:0] snapshot_o;

  freelist #(.NUM_PREGS(NUM_PREGS), .PREG_W(PREG_W)) dut (
      .clk(clk), .reset(reset),
      .alloc_req(alloc_req), .alloc_valid(alloc_valid), .alloc_preg(alloc_preg),
      .dealloc_valid(dealloc_valid), .dealloc_preg(dealloc_preg),
      .br_snapshot(br_snapshot), .br_rollback(br_rollback),
      .free_mask_o(free_mask_o), .snapshot_o(snapshot_o));

  `include "checker.vh"

  integer     cycle = 0;
  integer     fails = 0;
  integer     n_cycles = 2000;
  integer     max_fails = 5;
  reg [31:0]  seed = 32'd1;

  always #5 clk = ~clk;
  always @(posedge clk) cycle <= cycle + 1;

  task chk(input [8*16-1:0] name, input ok);
    begin
      if (ok !== 1'b1) begin
        fails = fails + 1;
        $display("ASSERT_FAIL prop=%0s cycle=%0d", name, cycle);
        if (fails >= max_fails) begin
          $display("SUMMARY cycles=%0d fails=%0d", cycle, fails);
          $display("RESULT FAIL");
          $finish;
        end
      end
    end
  endtask

  // Return the index of a randomly chosen set bit, or -1 if mask is empty.
  function integer pick_set_bit(input [NUM_PREGS-1:0] mask, input [31:0] r);
    integer k, cnt, idx;
    begin
      cnt = 0;
      for (k = 0; k < NUM_PREGS; k = k + 1) if (mask[k]) cnt = cnt + 1;
      if (cnt == 0) pick_set_bit = -1;
      else begin
        idx = r % cnt;
        pick_set_bit = -1;
        cnt = 0;
        for (k = 0; k < NUM_PREGS; k = k + 1) begin
          if (mask[k]) begin
            if (cnt == idx && pick_set_bit < 0) pick_set_bit = k;
            cnt = cnt + 1;
          end
        end
      end
    end
  endfunction

  task drive;
    reg [31:0] r;
    integer    d;
    begin
      r = $random(seed);
      if ((r % 100) < 8 && started) begin
        // A2: rollback is exclusive of allocation and deallocation.
        br_rollback   = 1'b1;
        alloc_req     = 1'b0;
        dealloc_valid = 1'b0;
        br_snapshot   = 1'b0;
      end else begin
        br_rollback = 1'b0;

        r = $random(seed);
        alloc_req = ((r % 100) < 50);

        r = $random(seed);
        if ((r % 100) < 40) begin
          // A1: only deallocate a preg the spec believes is allocated.
          r = $random(seed);
          d = pick_set_bit(shadow_alloc, r);
          if (d >= 0) begin
            dealloc_valid = 1'b1;
            dealloc_preg  = d[PREG_W-1:0];
          end else dealloc_valid = 1'b0;
        end else dealloc_valid = 1'b0;

        r = $random(seed);
        br_snapshot = ((r % 100) < 12);
      end
    end
  endtask

  always @(negedge clk) begin
    if (!reset) begin
      // State properties: sampled on the post-edge state.
      chk("P1_mutex",     p1_mutex);
      chk("P2_complete",  p2_complete);
      chk("P4_rollback",  p4_rollback);
      chk("P6_snap_mutex",    p6_snap_mutex);
      chk("P7_snap_complete", p7_snap_complete);
    end
    if (!reset) drive;
    #1;
    if (!reset) begin
      // Input-dependent properties: sampled with this cycle's stimulus applied.
      chk("P3_no_dbl",    p3_no_dbl);
      chk("P5_alloc_iff", p5_alloc_iff);
    end
  end

  initial begin
    if (!$value$plusargs("cycles=%d", n_cycles))  n_cycles  = 2000;
    if (!$value$plusargs("seed=%d",   seed))      seed      = 32'd1;
    if (!$value$plusargs("maxfail=%d", max_fails)) max_fails = 5;

    repeat (3) @(posedge clk);
    reset = 1'b0;

    while (cycle < n_cycles) @(posedge clk);

    $display("SUMMARY cycles=%0d fails=%0d", cycle, fails);
    $display("RESULT %0s", (fails == 0) ? "PASS" : "FAIL");
    $finish;
  end

endmodule
