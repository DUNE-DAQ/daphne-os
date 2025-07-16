`timescale 1ns / 10ps
//////////////////////////////////////////////////////////////////////////////////
// University: UNIMIB 
// Engineer: Esteban Cristaldo, MSc
//
// Create Date: July 22, 2022, 1:50:22 PM
// Design Name: filtering_and_selftrigger
// Module Name: IIRFilter_afe_integrator_optimized.v
// Project Name: selftrigger@bicocca
// Target Devices: DAPHNE V2
//
//////////////////////////////////////////////////////////////////////////////////


module IIRFilter_afe_integrator_optimized(
    input wire clk,
  	input wire reset,
    input wire enable,
    input wire signed[15:0] x,
    output wire signed[15:0] y
    );

    reg signed [17:0] n1, n2, n3, d1, d2;
    reg signed [24:0] x_1, x_2, y_1, y_2;
  	reg signed[15:0] x_i, en_mux;
  	reg enable_reg, reset_reg;

  	wire signed[24:0] w1, w4, w7, w12, w13, w15;
  	wire signed [17:0] w2, w20, w8, w14, w16;
  	wire signed[47:0] w3, w5, w9, w6, w10, w11, w17, w18, w19;

  	initial begin 
  		reset_reg <= 1'b0; 
	    enable_reg <= 1'b0;
	    // These coefficients correspond to the AFE compesator filter
	    n1 <= {3'b001,15'b000000000000000}; 
		n2 <= {3'b110,15'b000100101101100};
		n3 <= {3'b000,15'b111011010101110}; 
		d1 <= {3'b001,15'b110111101000100}; 
		d2 <= {3'b111,15'b001000010011110};
		x_i <= 16'b0;
	    x_1 <= 25'b0;
	    x_2 <= 25'b0;
		y_1 <= 25'b0;
		y_2 <= 25'b0;
		en_mux <= 16'b0;
  	end 
  	
  	always @(posedge clk) begin
	   reset_reg <= reset; 
	   enable_reg <= enable;
	end

	always @(posedge clk) begin
		if(reset_reg) begin
			// These coefficients correspond to the AFE compesator filter
			n1 <= {3'b001,15'b000000000000000}; 
			n2 <= {3'b110,15'b000100101101100};
			n3 <= {3'b000,15'b111011010101110}; 
			d1 <= {3'b001,15'b110111101000100}; 
			d2 <= {3'b111,15'b001000010011110};
			x_i <= 16'b0;
            x_1 <= 25'b0;
            x_2 <= 25'b0;
			y_1 <= 25'b0;
			y_2 <= 25'b0;
		end else if (enable_reg) begin
		    x_i <= x;
			x_1 <= w1;
			x_2 <= w4;
			y_1 <= w12;
			y_2 <= w13;
		end
	end

    always @(posedge clk) begin
		if(enable) begin
			en_mux <= w11[39:24];
      //en_mux <= w11[40:25];
		end else begin
			en_mux <= x;
		end
	end

	assign w1 = {x_i,9'b0};
  //assign w1 = {1'b0,x_i[13:0],10'b0};
  assign w2 = n1;
  assign w3 = (w1*w2);
  assign w4 = x_1;
  assign w20 = n2;
  assign w5 = (w4*w20);
  assign w7 = x_2;
  assign w8 = n3;
  assign w9 = (w7*w8);
  assign w6 = w3 + w5;
  assign w10 = w6 + w9;
  assign w11 = w19 + w10;
  //assign w12 = w11[40:15];
  assign w12 = w11[39:15];
  assign w13 = y_1;
  assign w14 = d1;
  assign w15 = y_2;
  assign w16 = d2;
  assign w17 = (w15*w16);
  assign w18 = (w13*w14);
  assign w19 = w18 + w17;
  assign y = en_mux;

endmodule